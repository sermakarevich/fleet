"""Tests for state/task_actions.py — file edits behind moderation endpoints."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fleet.state import task_actions
from fleet.state.task_actions import TaskNotFound


class FakeQueue:
    """Structural TaskQueue recording calls (beads satisfies the same shape)."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def release(self, task_id: str, reason: str = "", wait_sec: int = 0) -> None:
        """Record a release call."""
        self.calls.append(("release", task_id, reason))

    def close(self, task_id: str, reason: str = "completed") -> None:
        """Record a close call."""
        self.calls.append(("close", task_id, reason))


def _write_task(task_dir: Path, **fields) -> Path:
    task_dir.mkdir(parents=True, exist_ok=True)
    data = {"id": task_dir.name, "title": "T", "status": "blocked"}
    data.update(fields)
    (task_dir / "task.json").write_text(json.dumps(data))
    return task_dir


def test_unblock_releases_and_clears_retry_state(tmp_path: Path) -> None:
    """unblock releases with the note, clears retry_after/validation, journals."""
    task_dir = _write_task(
        tmp_path / "tasks" / "t-unblock", retry_after="2099-01-01T00:00:00+00:00"
    )
    (task_dir / ".needs_validation").write_text("1")
    queue = FakeQueue()

    task_actions.unblock(tmp_path, queue, "t-unblock", "looks fine")

    assert queue.calls == [("release", "t-unblock", "[fleet] unblocked from UI: looks fine")]
    assert "retry_after" not in (task_dir / "task.json").read_text()
    assert not (task_dir / ".needs_validation").exists()
    rows = (task_dir / "attempts.jsonl").read_text().splitlines()
    assert json.loads(rows[-1])["event"] == "unblock"


def test_unblock_missing_task_raises(tmp_path: Path) -> None:
    """unblock on an unknown id raises TaskNotFound without touching the queue."""
    queue = FakeQueue()
    with pytest.raises(TaskNotFound):
        task_actions.unblock(tmp_path, queue, "nope", None)
    assert queue.calls == []


def test_kill_running_touches_sentinel(tmp_path: Path) -> None:
    """kill on in_progress writes .kill; outcome depends on supervisor liveness."""
    _write_task(tmp_path / "tasks" / "t-run", status="in_progress")
    queue = FakeQueue()

    assert (
        task_actions.kill(tmp_path, queue, "t-run", status="in_progress", supervisor_running=True)
        == "killing"
    )
    assert (tmp_path / "tasks" / "t-run" / ".kill").exists()
    assert queue.calls == []

    _write_task(tmp_path / "tasks" / "t-run2", status="in_progress")
    assert (
        task_actions.kill(tmp_path, queue, "t-run2", status="in_progress", supervisor_running=False)
        == "supervisor-not-running"
    )
    assert (tmp_path / "tasks" / "t-run2" / ".kill").exists()


def test_kill_queued_closes_without_sentinel(tmp_path: Path) -> None:
    """kill on open/ready/blocked closes via the queue and writes no sentinel."""
    task_dir = _write_task(tmp_path / "tasks" / "t-q", status="open")
    queue = FakeQueue()

    assert (
        task_actions.kill(tmp_path, queue, "t-q", status="open", supervisor_running=True)
        == "closed"
    )
    assert queue.calls == [("close", "t-q", "killed")]
    assert not (task_dir / ".kill").exists()


def test_kill_terminal_is_noop_and_missing_raises(tmp_path: Path) -> None:
    """kill on closed is a no-op; unknown ids raise TaskNotFound."""
    _write_task(tmp_path / "tasks" / "t-done", status="closed")
    queue = FakeQueue()

    assert (
        task_actions.kill(tmp_path, queue, "t-done", status="closed", supervisor_running=True)
        == "no-op"
    )
    assert queue.calls == []
    with pytest.raises(TaskNotFound):
        task_actions.kill(tmp_path, queue, "nope", status="open", supervisor_running=True)


def test_remove_assignee_clears_mirror(tmp_path: Path) -> None:
    """remove_assignee clears beads (via callback) and the coder mirror."""
    task_dir = _write_task(tmp_path / "tasks" / "t-a", coder="claude")
    cleared: list[str] = []

    task_actions.remove_assignee(tmp_path, "t-a", clear_assignee=cleared.append)

    assert cleared == ["t-a"]
    assert "claude" not in (task_dir / "task.json").read_text()


def test_remove_assignee_missing_raises_before_callback(tmp_path: Path) -> None:
    """Unknown ids raise TaskNotFound and never reach the beads callback."""
    cleared: list[str] = []
    with pytest.raises(TaskNotFound):
        task_actions.remove_assignee(tmp_path, "nope", clear_assignee=cleared.append)
    assert cleared == []
