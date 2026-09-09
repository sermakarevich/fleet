"""WebSocket event streaming pipeline for fleet serve (FR-03, FR-06, FR-10, FR-13)."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from fastapi import WebSocket

from fleet.core.limits import SERVE_WATCH_INTERVAL_SEC, WS_REPLAY_LINES
from fleet.core.redact import redact
from fleet.core.task import EventKind
from fleet.state.attempts import latest_attempt_dir
from fleet.state.incremental_read import read_new_bytes
from fleet.state.runtime_stats import task_files_touched, task_runtime_stats
from fleet.state.task_index import TaskIndex
from fleet.state.task_meta import TaskMeta

logger = logging.getLogger(__name__)


@dataclass
class _TailState:
    offset: int  # byte position in events.jsonl
    path: Path  # the attempt's events.jsonl this state belongs to


class WebSocketBroadcaster:
    def __init__(self) -> None:
        self._global: set[WebSocket] = set()
        self._per_task: dict[str, set[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, task_id: str | None = None) -> None:
        await websocket.accept()
        if task_id is None:
            self._global.add(websocket)
        else:
            self._per_task.setdefault(task_id, set()).add(websocket)

    async def disconnect(self, websocket: WebSocket) -> None:
        self._global.discard(websocket)
        for s in self._per_task.values():
            s.discard(websocket)

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
            except Exception as exc:
                logger.debug("watcher send failed (global subscriber)", exc_info=exc)
                dead.add(ws)
        for ws in list(self._per_task.get(task_id, set())):
            try:
                await ws.send_json(task_msg)
            except Exception as exc:
                logger.debug("watcher send failed", exc_info=exc, extra={"task_id": task_id})
                dead.add(ws)
        for ws in dead:
            await self.disconnect(ws)


def _list_task_dirs(index: TaskIndex) -> list[Path]:
    """Snapshot of task dirs (runs in a thread; walks tasks/)."""
    return list(index.iter_dirs())


def _stat_size(path: Path) -> int | None:
    """File size, None when the file raced away (runs in a thread)."""
    try:
        return path.stat().st_size
    except OSError:
        return None


def _read_all(path: Path) -> bytes:
    """Whole file bytes, b"" when unreadable (runs in a thread)."""
    try:
        return path.read_bytes()
    except OSError:
        return b""


@dataclass
class FileWatcher:
    """Tail attempt events.jsonl files and broadcast new events over websockets."""

    mgr: WebSocketBroadcaster
    _tail_state: dict[str, _TailState] = field(default_factory=dict)

    async def start(self, fleet_home: Path) -> None:
        """Tail the latest attempt's events.jsonl for all task dirs until cancelled."""
        index = TaskIndex(fleet_home)
        while True:
            try:
                task_dirs = await asyncio.to_thread(_list_task_dirs, index)
                for task_dir in task_dirs:
                    try:
                        await self._tail_task(task_dir)
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        logger.exception("watcher task error", extra={"task_id": task_dir.name})
                await asyncio.to_thread(self._prune_stale, index.tasks_dir)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("watcher cycle error")
            await asyncio.sleep(SERVE_WATCH_INTERVAL_SEC)

    async def _tail_task(self, task_dir: Path) -> None:
        """Tail one task's latest attempt events file (no-op when absent)."""
        attempt_dir = await asyncio.to_thread(latest_attempt_dir, task_dir)
        if attempt_dir is None:
            return
        events_file = attempt_dir / "events.jsonl"
        if events_file.exists():
            await self._tail_one(task_dir, task_dir.name, events_file)

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

    async def _replay_tail(
        self, task_id: str, path: Path, tail_lines: int = WS_REPLAY_LINES
    ) -> None:
        """Broadcast the last `tail_lines` events from path (replay on serve restart)."""
        data = await asyncio.to_thread(_read_all, path)
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
        size = await asyncio.to_thread(_stat_size, path)
        if size is None:
            return

        state = self._tail_state.get(task_id)
        if state is None or state.path != path:
            # First encounter of this task, or a new attempt started (new
            # events.jsonl file): replay recent events for in-progress tasks,
            # then tail from EOF.
            meta = await asyncio.to_thread(TaskMeta.load, task_dir)
            if meta is not None and meta.status == "in_progress":
                await self._replay_tail(task_id, path)
            self._tail_state[task_id] = _TailState(offset=size, path=path)
            return

        new_data, new_offset = await asyncio.to_thread(read_new_bytes, path, state.offset)
        if not new_data:
            return

        self._tail_state[task_id] = _TailState(offset=new_offset, path=path)
        for line_bytes in new_data.splitlines():
            stripped = line_bytes.strip()
            if not stripped:
                continue
            try:
                event_dict = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            if event_dict.get("kind") == EventKind.SESSION_ENDED:
                event_dict = await asyncio.to_thread(
                    self._enrich_session_ended, task_id, task_dir, event_dict
                )
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

        stats = task_runtime_stats(task_dir)
        duration_sec: float | None = None
        if stats.started_at is not None:
            duration_sec = (datetime.now(tz=UTC) - stats.started_at).total_seconds()

        files_touched = task_files_touched(task_dir)

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
