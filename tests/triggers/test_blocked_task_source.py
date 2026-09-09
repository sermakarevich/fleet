"""Tests for the `blocked_task` event source (ADR 0011 first source)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from fleet.state import paths as state_paths
from fleet.state.task_meta import TaskMeta
from fleet.triggers.model import TriggerEvent
from fleet.triggers.sources import UnknownSource, source_for, source_params
from fleet.triggers.sources.base import SourceContext
from fleet.triggers.sources.blocked_task import BlockedTaskSource
from tests.conftest import FakeQueue

NOW = datetime(2026, 9, 9, 12, 0, 0, tzinfo=UTC)
BLOCKED_AT = "2026-09-09T11:00:00+00:00"


def _write_meta(fleet_home: Path, task_id: str, **fields: Any) -> Path:
    """Write task.json for a bead; extra keys (ignore_until, ...) land in extra."""
    task_dir = state_paths.task_dir(fleet_home, task_id)
    task_dir.mkdir(parents=True, exist_ok=True)
    TaskMeta.update(task_dir, **fields)
    return task_dir


def _ctx(fleet_home: Path, queue: FakeQueue, **params: str) -> SourceContext:
    return SourceContext(fleet_home=fleet_home, queue=queue, now=NOW, params=dict(params))


def _blocked(queue: FakeQueue, fleet_home: Path, title: str = "stuck", **meta: Any) -> str:
    """Open a task, mark it blocked, and write its task.json."""
    task = queue.create_task(title)
    queue.set_blocked(task.id, "blocked")
    _write_meta(fleet_home, task.id, title=title, **meta)
    return task.id


def test_fleet_blocked_emits_event(tmp_path: Path) -> None:
    queue = FakeQueue()
    task_id = _blocked(
        queue,
        tmp_path,
        blocked_reason="needs help",
        blocked_at=BLOCKED_AT,
        title="stuck",
        cwd="/repo",
        coder="opencode",
        model="m",
    )
    events = BlockedTaskSource().poll(_ctx(tmp_path, queue))
    assert len(events) == 1
    event = events[0]
    assert isinstance(event, TriggerEvent)
    assert event.source == "blocked_task"
    assert event.key == f"{task_id}@{BLOCKED_AT}"
    assert event.occurred_at == BLOCKED_AT
    assert event.payload["task_id"] == task_id
    assert event.payload["title"] == "stuck"
    assert event.payload["blocked_reason"] == "needs help"
    assert event.payload["blocked_at"] == BLOCKED_AT
    assert event.payload["cwd"] == "/repo"
    assert event.payload["coder"] == "opencode"
    assert event.payload["model"] == "m"
    assert event.payload["task_dir"] == str(state_paths.task_dir(tmp_path, task_id).absolute())
    assert event.payload["rounds"] == str(
        {"failure": 0, "stall": 0, "context": 0, "partial": 0, "noclose": 0}
    )
    assert event.payload["result_status"] == ""
    assert event.payload["stderr_tail"] == ""
    assert all(isinstance(v, str) for v in event.payload.values())


def test_human_blocked_skipped_by_default(tmp_path: Path) -> None:
    queue = FakeQueue()
    task_id = _blocked(queue, tmp_path, title="manual")
    assert BlockedTaskSource().poll(_ctx(tmp_path, queue)) == []
    events = BlockedTaskSource().poll(_ctx(tmp_path, queue, fleet_blocked_only="false"))
    assert [e.key for e in events] == [f"{task_id}@unknown"]
    assert events[0].occurred_at == NOW.isoformat()


def test_active_ignore_skipped(tmp_path: Path) -> None:
    queue = FakeQueue()
    _blocked(queue, tmp_path, blocked_reason="x", blocked_at=BLOCKED_AT, ignore_until="forever")
    assert BlockedTaskSource().poll(_ctx(tmp_path, queue)) == []


def test_trigger_opened_bead_skipped(tmp_path: Path) -> None:
    queue = FakeQueue()
    _blocked(
        queue,
        tmp_path,
        blocked_reason="x",
        blocked_at=BLOCKED_AT,
        fleet_trigger_id="trg-abc123",
    )
    assert BlockedTaskSource().poll(_ctx(tmp_path, queue)) == []


def test_queue_error_returns_empty(tmp_path: Path) -> None:
    class BadQueue(FakeQueue):
        def list_blocked(self, limit: int = 100) -> list:
            raise RuntimeError("boom")

    assert BlockedTaskSource().poll(_ctx(tmp_path, BadQueue())) == []


def test_source_for_registry() -> None:
    assert isinstance(source_for("blocked_task"), BlockedTaskSource)
    with pytest.raises(UnknownSource):
        source_for("nope")
    params = source_params("blocked_task")
    assert params == BlockedTaskSource.PARAMS
    assert source_params("nope") == {}
