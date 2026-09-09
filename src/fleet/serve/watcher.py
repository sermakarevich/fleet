"""WebSocket event streaming pipeline for fleet serve (FR-03, FR-06, FR-10, FR-13)."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from fastapi import WebSocket

from fleet.core.redact import redact
from fleet.core.task import EventKind
from fleet.state.attempts import latest_attempt_dir
from fleet.state.runtime_stats import task_files_touched_from_dir, task_runtime_stats_from_dir
from fleet.state.tail import read_new_bytes
from fleet.state.task_index import TaskIndex
from fleet.state.task_meta import TaskMeta


@dataclass
class _TailState:
    offset: int  # byte position in events.jsonl
    mtime: float  # last observed st_mtime
    path: Path  # the attempt's events.jsonl this state belongs to


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


@dataclass
class FileWatcher:
    """Tail attempt events.jsonl files and broadcast new events over websockets."""

    mgr: ConnectionManager
    _tail_state: dict[str, _TailState] = field(default_factory=dict)

    async def start(self, fleet_home: Path) -> None:
        """Tail the latest attempt's events.jsonl for all task dirs until cancelled."""
        index = TaskIndex(fleet_home)
        while True:
            for task_dir in index.iter_dirs():
                attempt_dir = latest_attempt_dir(task_dir)
                if attempt_dir is None:
                    continue
                events_file = attempt_dir / "events.jsonl"
                if events_file.exists():
                    await self._tail_one(task_dir, task_dir.name, events_file)
            self._prune_stale(index.tasks_dir)
            await asyncio.sleep(0.2)

    def _prune_stale(self, tasks_dir: Path) -> None:
        """Drop _tail_state entries whose task directory no longer exists."""
        existing = (
            {p.name for p in TaskIndex(tasks_dir.parent).iter_dirs()}
            if tasks_dir.exists()
            else set()
        )
        for task_id in list(self._tail_state):
            if task_id not in existing:
                del self._tail_state[task_id]

    async def _replay_tail(self, task_id: str, path: Path, tail_lines: int = 50) -> None:
        """Broadcast the last `tail_lines` events from path (replay on serve restart)."""
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
            await self.mgr.broadcast(task_id, redact(event_dict))

    async def _tail_one(self, task_dir: Path, task_id: str, path: Path) -> None:
        """Read new bytes from path since last offset and broadcast each parsed event.

        *path* is the latest attempt's events.jsonl; *task_dir* is the task
        root (where task.json lives and where state.events aggregates across
        all attempts for enrichment).
        """
        try:
            stat = path.stat()
        except OSError:
            return

        state = self._tail_state.get(task_id)
        if state is None or state.path != path:
            # First encounter of this task, or a new attempt started (new
            # events.jsonl file): replay recent events for in-progress tasks,
            # then tail from EOF.
            meta = TaskMeta.load(task_dir)
            if meta is not None and meta.status == "in_progress":
                await self._replay_tail(task_id, path)
            self._tail_state[task_id] = _TailState(
                offset=stat.st_size, mtime=stat.st_mtime, path=path
            )
            return

        new_data, new_offset = read_new_bytes(path, state.offset)
        if not new_data:
            return

        self._tail_state[task_id] = _TailState(offset=new_offset, mtime=stat.st_mtime, path=path)
        for line_bytes in new_data.splitlines():
            stripped = line_bytes.strip()
            if not stripped:
                continue
            try:
                event_dict = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            if event_dict.get("kind") == EventKind.SESSION_ENDED:
                event_dict = self._enrich_session_ended(task_id, task_dir, event_dict)
            await self.mgr.broadcast(task_id, redact(event_dict))

    def _enrich_session_ended(self, task_id: str, task_dir: Path, event_dict: dict) -> dict:
        """Inject summary stats into a session_ended event before broadcast."""
        raw = event_dict.get("raw") or {}
        subtype = raw.get("subtype") or ""
        result = subtype or ("failure" if raw.get("is_error") else "success")

        task_title: str = task_id
        meta = TaskMeta.load(task_dir)
        if meta is not None and meta.title:
            task_title = meta.title

        stats = task_runtime_stats_from_dir(task_dir)
        duration_sec: float | None = None
        if stats.started_at is not None:
            duration_sec = (datetime.now(tz=UTC) - stats.started_at).total_seconds()

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
