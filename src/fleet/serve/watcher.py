"""WebSocket event streaming pipeline for fleet serve (FR-03, FR-06, FR-10, FR-13)."""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from fastapi import WebSocket

from fleet.redact import redact
from fleet.serve.stats import task_files_touched_from_dir, task_runtime_stats_from_dir


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


def _read_task_status(task_json: Path) -> str | None:
    """Return the status field from task.json, or None if unavailable."""
    try:
        data = json.loads(task_json.read_bytes())
        return data.get("status") if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError, AttributeError):
        return None


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
            self._prune_stale(tasks_dir)
            await asyncio.sleep(0.2)

    def _prune_stale(self, tasks_dir: Path) -> None:
        """Drop _tail_state entries whose task directory no longer exists."""
        existing = (
            {d.name for d in tasks_dir.iterdir() if d.is_dir()}
            if tasks_dir.exists()
            else set()
        )
        for task_id in list(self._tail_state):
            if task_id not in existing:
                del self._tail_state[task_id]

    async def _replay_tail(self, task_id: str, path: Path, tail_lines: int = 50) -> None:
        """Broadcast the last `tail_lines` events from path (replay on serve restart)."""
        assert self._mgr is not None
        try:
            data = path.read_bytes()
        except OSError:
            return
        lines = [ln for ln in data.splitlines() if ln.strip()]
        for line_bytes in lines[-tail_lines:]:
            try:
                event_dict = json.loads(line_bytes)
            except json.JSONDecodeError:
                continue
            await self._mgr.broadcast(task_id, redact(event_dict))

    async def _tail_one(self, task_id: str, path: Path) -> None:
        """Read new bytes from path since last offset and broadcast each parsed event."""
        assert self._mgr is not None
        try:
            stat = path.stat()
        except OSError:
            return

        state = self._tail_state.get(task_id)
        if state is None:
            # On first encounter: replay recent events for in-progress tasks, then tail from EOF.
            if _read_task_status(path.parent / "task.json") == "in_progress":
                await self._replay_tail(task_id, path)
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
            if event_dict.get("kind") == "session_ended":
                event_dict = self._enrich_session_ended(task_id, path.parent, event_dict)
            await self._mgr.broadcast(task_id, redact(event_dict))

    def _enrich_session_ended(self, task_id: str, task_dir: Path, event_dict: dict) -> dict:
        """Inject summary stats into a session_ended event before broadcast."""
        raw = event_dict.get("raw") or {}
        subtype = raw.get("subtype") or ""
        if subtype:
            result = subtype
        else:
            result = "failure" if raw.get("is_error") else "success"

        task_title: str = task_id
        task_file = task_dir / "task.json"
        if task_file.exists():
            try:
                data = json.loads(task_file.read_text("utf-8"))
                task_title = data.get("title") or task_id
            except (OSError, json.JSONDecodeError):
                pass

        stats = task_runtime_stats_from_dir(task_dir)
        duration_sec: float | None = None
        if stats.started_at is not None:
            duration_sec = (datetime.now(tz=timezone.utc) - stats.started_at).total_seconds()

        files_touched = task_files_touched_from_dir(task_dir)

        return {
            **event_dict,
            "extra": {
                "result": result,
                "task_title": task_title,
                "duration_sec": duration_sec,
                "files_touched": files_touched,
                "context_tokens": stats.context_tokens,
            },
        }
