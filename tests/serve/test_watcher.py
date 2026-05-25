"""Tests for FileWatcher event streaming pipeline (FR-03, FR-06, FR-10)."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from fleet.serve.watcher import ConnectionManager, FileWatcher


def test_file_watcher_detects_new_line(tmp_path: Path) -> None:
    """FileWatcher broadcasts newly written events from events.jsonl (FR-03, FR-10)."""
    task_id = "task-abc"
    task_dir = tmp_path / "tasks" / task_id
    task_dir.mkdir(parents=True)
    events_file = task_dir / "events.jsonl"
    events_file.touch()

    mgr = MagicMock()
    mgr.broadcast = AsyncMock()

    watcher = FileWatcher()
    watcher._mgr = mgr

    async def _run() -> None:
        # First call: initializes tail state (offset=0 for empty file) and returns
        await watcher._tail_one(task_id, events_file)
        assert not mgr.broadcast.called

        # Append a new event line
        event_data = {
            "kind": "tool_use",
            "ts": "2026-05-25T12:00:00+00:00",
            "session_id": None,
            "tool_name": "Edit",
            "usage": None,
            "rate_info": None,
            "raw": {"path": "src/foo.py"},
        }
        with events_file.open("a") as f:
            f.write(json.dumps(event_data) + "\n")

        # Second call: reads new line and broadcasts
        await watcher._tail_one(task_id, events_file)

    asyncio.run(_run())

    mgr.broadcast.assert_called_once()
    call_task_id, broadcasted = mgr.broadcast.call_args[0]
    assert call_task_id == task_id
    assert broadcasted["kind"] == "tool_use"
    assert broadcasted["tool_name"] == "Edit"
    assert broadcasted["raw"] == {"path": "src/foo.py"}


def test_file_watcher_redacts_credentials(tmp_path: Path) -> None:
    """Credentials in raw events are redacted before broadcasting."""
    task_id = "task-cred"
    task_dir = tmp_path / "tasks" / task_id
    task_dir.mkdir(parents=True)
    events_file = task_dir / "events.jsonl"
    events_file.touch()

    mgr = MagicMock()
    mgr.broadcast = AsyncMock()

    watcher = FileWatcher()
    watcher._mgr = mgr

    async def _run() -> None:
        await watcher._tail_one(task_id, events_file)
        event_data = {
            "kind": "tool_use",
            "ts": "2026-05-25T12:00:00+00:00",
            "session_id": None,
            "tool_name": "Bash",
            "usage": None,
            "rate_info": None,
            "raw": {"cmd": "echo hello", "ANTHROPIC_API_KEY": "sk-secret"},
        }
        with events_file.open("a") as f:
            f.write(json.dumps(event_data) + "\n")
        await watcher._tail_one(task_id, events_file)

    asyncio.run(_run())

    mgr.broadcast.assert_called_once()
    broadcasted = mgr.broadcast.call_args[0][1]
    assert broadcasted["raw"]["ANTHROPIC_API_KEY"] == "<redacted>"
    assert broadcasted["raw"]["cmd"] == "echo hello"


def test_file_watcher_skips_invalid_json(tmp_path: Path) -> None:
    """Malformed JSON lines are silently skipped; valid lines still broadcast."""
    task_id = "task-bad"
    task_dir = tmp_path / "tasks" / task_id
    task_dir.mkdir(parents=True)
    events_file = task_dir / "events.jsonl"
    events_file.touch()

    mgr = MagicMock()
    mgr.broadcast = AsyncMock()

    watcher = FileWatcher()
    watcher._mgr = mgr

    async def _run() -> None:
        await watcher._tail_one(task_id, events_file)
        with events_file.open("a") as f:
            f.write("not valid json\n")
            f.write(
                json.dumps({
                    "kind": "assistant_text",
                    "ts": "2026-05-25T12:00:00+00:00",
                    "session_id": None,
                    "tool_name": None,
                    "usage": None,
                    "rate_info": None,
                    "raw": {},
                }) + "\n"
            )
        await watcher._tail_one(task_id, events_file)

    asyncio.run(_run())

    assert mgr.broadcast.call_count == 1
    assert mgr.broadcast.call_args[0][1]["kind"] == "assistant_text"


def test_connection_manager_removes_disconnected_on_broadcast() -> None:
    """broadcast() silently removes clients that raise on send_json."""

    async def _run() -> None:
        mgr = ConnectionManager()

        good_ws = MagicMock()
        good_ws.accept = AsyncMock()
        good_ws.send_json = AsyncMock()

        dead_ws = MagicMock()
        dead_ws.accept = AsyncMock()
        dead_ws.send_json = AsyncMock(side_effect=RuntimeError("closed"))

        await mgr.connect(good_ws)
        await mgr.connect(dead_ws)

        # First broadcast — dead_ws raises, gets removed silently
        await mgr.broadcast("task-1", {"kind": "tool_use"})
        assert good_ws.send_json.call_count == 1

        # Second broadcast — dead_ws is gone, only good_ws receives
        await mgr.broadcast("task-1", {"kind": "assistant_text"})
        assert good_ws.send_json.call_count == 2
        assert dead_ws.send_json.call_count == 1

    asyncio.run(_run())
