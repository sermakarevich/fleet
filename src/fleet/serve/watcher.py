"""WebSocket event streaming pipeline for fleet serve (FR-03, FR-06, FR-10, FR-13)."""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path

from fastapi import WebSocket

from fleet.redact import redact


@dataclass
class _TailState:
    offset: int   # byte position in events.jsonl
    mtime: float  # last observed st_mtime


class ConnectionManager:
    def __init__(self) -> None:
        self._global: set[WebSocket] = set()
        self._per_task: dict[str, set[WebSocket]] = {}

    async def connect(self, ws: WebSocket, task_id: str | None = None) -> None:
        await ws.accept()
        if task_id is None:
            self._global.add(ws)
        else:
            self._per_task.setdefault(task_id, set()).add(ws)

    async def disconnect(self, ws: WebSocket) -> None:
        self._global.discard(ws)
        for s in self._per_task.values():
            s.discard(ws)

    async def broadcast(self, task_id: str, payload: dict) -> None:
        """Send payload to all subscribers. Silently removes disconnected clients.

        Global subscribers receive {"task_id": ..., "event": payload}.
        Per-task subscribers receive {"event": payload}.
        """
        global_msg = {"task_id": task_id, "event": payload}
        task_msg = {"event": payload}
        dead: set[WebSocket] = set()
        for ws in list(self._global):
            try:
                await ws.send_json(global_msg)
            except Exception:
                dead.add(ws)
        for ws in list(self._per_task.get(task_id, set())):
            try:
                await ws.send_json(task_msg)
            except Exception:
                dead.add(ws)
        for ws in dead:
            await self.disconnect(ws)


class FileWatcher:
    def __init__(self) -> None:
        self._tail_state: dict[str, _TailState] = {}
        self._mgr: ConnectionManager | None = None

    async def start(self, fleet_home: Path, mgr: ConnectionManager) -> None:
        """Tail events.jsonl for all task dirs until cancelled."""
        self._mgr = mgr
        while True:
            tasks_dir = fleet_home / "tasks"
            if tasks_dir.exists():
                for task_dir in tasks_dir.iterdir():
                    if task_dir.is_dir():
                        events_file = task_dir / "events.jsonl"
                        if events_file.exists():
                            await self._tail_one(task_dir.name, events_file)
            await asyncio.sleep(0.2)

    async def _tail_one(self, task_id: str, path: Path) -> None:
        """Read new bytes from path since last offset and broadcast each parsed event."""
        assert self._mgr is not None
        try:
            stat = path.stat()
        except OSError:
            return

        state = self._tail_state.get(task_id)
        if state is None:
            # On first encounter, skip existing content — only tail new lines.
            self._tail_state[task_id] = _TailState(offset=stat.st_size, mtime=stat.st_mtime)
            return

        if stat.st_size <= state.offset:
            return

        try:
            with path.open("rb") as fh:
                fh.seek(state.offset)
                new_data = fh.read()
        except OSError:
            return

        self._tail_state[task_id] = _TailState(
            offset=state.offset + len(new_data), mtime=stat.st_mtime
        )
        for line_bytes in new_data.splitlines():
            stripped = line_bytes.strip()
            if not stripped:
                continue
            try:
                event_dict = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            await self._mgr.broadcast(task_id, redact(event_dict))
