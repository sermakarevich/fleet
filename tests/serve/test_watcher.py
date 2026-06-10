"""Tests for FileWatcher event streaming pipeline (FR-03, FR-06, FR-10)."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from fleet.serve.watcher import ConnectionManager, FileWatcher, _TailState


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


def test_file_watcher_enriches_session_ended(tmp_path: Path) -> None:
    """session_ended events are enriched with an extra dict on broadcast."""
    task_id = "task-end"
    task_dir = tmp_path / "tasks" / task_id
    task_dir.mkdir(parents=True)

    (task_dir / "task.json").write_text(
        json.dumps({"id": task_id, "title": "My finishing task"})
    )
    (task_dir / "log.jsonl").write_text(
        json.dumps({"timestamp": "2026-01-01T00:00:00+00:00"}) + "\n"
    )

    events_file = task_dir / "events.jsonl"
    # Seed a tool_use so files_touched > 0
    tool_use_event = {
        "kind": "tool_use",
        "ts": "2026-01-01T00:30:00+00:00",
        "session_id": None,
        "tool_name": "Edit",
        "usage": None,
        "rate_info": None,
        "raw": {"tool_name": "Edit", "input": {"file_path": "/tmp/foo.py"}},
    }
    with events_file.open("w") as f:
        f.write(json.dumps(tool_use_event) + "\n")

    mgr = MagicMock()
    mgr.broadcast = AsyncMock()

    watcher = FileWatcher()
    watcher._mgr = mgr

    async def _run() -> None:
        # Prime offset past the tool_use line
        await watcher._tail_one(task_id, events_file)
        assert not mgr.broadcast.called

        session_ended_event = {
            "kind": "session_ended",
            "ts": "2026-01-01T01:00:00+00:00",
            "session_id": "sess-1",
            "tool_name": None,
            "usage": None,
            "rate_info": None,
            "raw": {
                "type": "result",
                "subtype": "success",
                "result": "Done!",
                "is_error": False,
            },
        }
        with events_file.open("a") as f:
            f.write(json.dumps(session_ended_event) + "\n")

        await watcher._tail_one(task_id, events_file)

    asyncio.run(_run())

    mgr.broadcast.assert_called_once()
    _, broadcasted = mgr.broadcast.call_args[0]
    assert broadcasted["kind"] == "session_ended"
    extra = broadcasted.get("extra")
    assert extra is not None, "session_ended should be enriched with extra"
    assert extra["result"] == "success"
    assert extra["task_title"] == "My finishing task"
    assert extra["files_touched"] == 1
    assert extra["duration_sec"] is not None
    assert "context_tokens" in extra


def test_file_watcher_non_session_ended_not_enriched(tmp_path: Path) -> None:
    """Non-session_ended events are not modified with extra."""
    task_id = "task-noenrich"
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
            "ts": "2026-01-01T00:00:00+00:00",
            "session_id": None,
            "tool_name": "Read",
            "usage": None,
            "rate_info": None,
            "raw": {"input": {"file_path": "/tmp/bar.py"}},
        }
        with events_file.open("a") as f:
            f.write(json.dumps(event_data) + "\n")
        await watcher._tail_one(task_id, events_file)

    asyncio.run(_run())

    mgr.broadcast.assert_called_once()
    _, broadcasted = mgr.broadcast.call_args[0]
    assert "extra" not in broadcasted


def test_replay_recent_events_for_in_progress_task(tmp_path: Path) -> None:
    """On first encounter of an in_progress task, broadcast the existing events."""
    task_id = "task-live"
    task_dir = tmp_path / "tasks" / task_id
    task_dir.mkdir(parents=True)
    (task_dir / "task.json").write_text(json.dumps({"id": task_id, "status": "in_progress"}))

    events_file = task_dir / "events.jsonl"
    existing_events = [
        {
            "kind": "tool_use", "ts": f"2026-01-01T00:00:{i:02d}+00:00",
            "tool_name": "Read", "session_id": None,
            "usage": None, "rate_info": None, "raw": {},
        }
        for i in range(3)
    ]
    with events_file.open("w") as f:
        for evt in existing_events:
            f.write(json.dumps(evt) + "\n")

    mgr = MagicMock()
    mgr.broadcast = AsyncMock()

    watcher = FileWatcher()
    watcher._mgr = mgr

    asyncio.run(watcher._tail_one(task_id, events_file))

    assert mgr.broadcast.call_count == 3
    assert all(c[0][1]["kind"] == "tool_use" for c in mgr.broadcast.call_args_list)


def test_no_replay_for_non_in_progress_task(tmp_path: Path) -> None:
    """On first encounter of a closed task, do not replay existing events."""
    task_id = "task-closed"
    task_dir = tmp_path / "tasks" / task_id
    task_dir.mkdir(parents=True)
    (task_dir / "task.json").write_text(json.dumps({"id": task_id, "status": "closed"}))

    events_file = task_dir / "events.jsonl"
    events_file.write_text(
        json.dumps({
            "kind": "tool_use", "ts": "2026-01-01T00:00:00+00:00",
            "tool_name": "Read", "session_id": None,
            "usage": None, "rate_info": None, "raw": {},
        }) + "\n"
    )

    mgr = MagicMock()
    mgr.broadcast = AsyncMock()

    watcher = FileWatcher()
    watcher._mgr = mgr

    asyncio.run(watcher._tail_one(task_id, events_file))

    mgr.broadcast.assert_not_called()


def test_replay_capped_at_50_lines(tmp_path: Path) -> None:
    """On first encounter, at most the 50 most recent events are replayed."""
    task_id = "task-many"
    task_dir = tmp_path / "tasks" / task_id
    task_dir.mkdir(parents=True)
    (task_dir / "task.json").write_text(json.dumps({"id": task_id, "status": "in_progress"}))

    events_file = task_dir / "events.jsonl"
    with events_file.open("w") as f:
        for i in range(60):
            evt = {
                "kind": "tool_use",
                "ts": f"2026-01-01T00:00:{i % 60:02d}+00:00",
                "tool_name": "Read", "session_id": None,
                "usage": None, "rate_info": None, "raw": {"seq": i},
            }
            f.write(json.dumps(evt) + "\n")

    mgr = MagicMock()
    mgr.broadcast = AsyncMock()

    watcher = FileWatcher()
    watcher._mgr = mgr

    asyncio.run(watcher._tail_one(task_id, events_file))

    assert mgr.broadcast.call_count == 50
    last_payload = mgr.broadcast.call_args[0][1]
    assert last_payload["raw"]["seq"] == 59


def test_prune_stale_removes_deleted_task_entry(tmp_path: Path) -> None:
    """_prune_stale drops tail-state entries for task directories that no longer exist."""
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()

    alive_dir = tasks_dir / "task-alive"
    alive_dir.mkdir()
    deleted_dir = tasks_dir / "task-deleted"
    deleted_dir.mkdir()

    watcher = FileWatcher()
    watcher._tail_state["task-alive"] = _TailState(offset=0, mtime=0.0)
    watcher._tail_state["task-deleted"] = _TailState(offset=0, mtime=0.0)

    deleted_dir.rmdir()
    watcher._prune_stale(tasks_dir)

    assert "task-alive" in watcher._tail_state
    assert "task-deleted" not in watcher._tail_state


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
