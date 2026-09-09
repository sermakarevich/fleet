"""Tests for already-closed task handling (unit under test: orchestrator reap guards)."""

from __future__ import annotations

from pathlib import Path

from fleet.core.retry_policy import NOCLOSE_MAX_ROUNDS
from fleet.core.task import TaskOutcome
from tests.orchestrator.conftest import StubQueue, _handle, _make_supervisor, _outcome, _task


def test_context_pressure_calls_release(tmp_path: Path) -> None:
    queue = StubQueue(status="in_progress")
    s = _make_supervisor(tmp_path, queue)
    _handle(s, _task(), _outcome(TaskOutcome.CONTEXT_PRESSURE))
    assert len(queue.released) == 1
    assert "context_pressure" in queue.released[0][1]


def test_context_pressure_third_round_blocks_with_split_hint(tmp_path: Path) -> None:
    queue = StubQueue(status="in_progress")
    s = _make_supervisor(tmp_path, queue)
    for _ in range(3):
        _handle(s, _task(), _outcome(TaskOutcome.CONTEXT_PRESSURE))
    assert len(queue.blocked) == 1
    assert "split it" in queue.blocked[0][1]


def test_context_pressure_closed_bead_no_release(tmp_path: Path) -> None:
    queue = StubQueue(status="closed")
    s = _make_supervisor(tmp_path, queue)
    _handle(s, _task(), _outcome(TaskOutcome.CONTEXT_PRESSURE))
    assert len(queue.released) == 0


def test_context_pressure_closed_bead_no_set_blocked(tmp_path: Path) -> None:
    queue = StubQueue(status="closed")
    s = _make_supervisor(tmp_path, queue)
    _handle(s, _task(), _outcome(TaskOutcome.CONTEXT_PRESSURE))
    assert len(queue.blocked) == 0


def test_failure_closed_bead_no_release(tmp_path: Path) -> None:
    queue = StubQueue(status="closed")
    s = _make_supervisor(tmp_path, queue)
    _handle(s, _task(), _outcome(TaskOutcome.FAILURE, exit_code=1))
    assert len(queue.released) == 0


def test_failure_closed_bead_no_set_blocked(tmp_path: Path) -> None:
    queue = StubQueue(status="closed")
    s = _make_supervisor(tmp_path, queue)
    _handle(s, _task(), _outcome(TaskOutcome.FAILURE, exit_code=1))
    assert len(queue.blocked) == 0


def test_failure_closed_bead_no_counter_files(tmp_path: Path) -> None:
    queue = StubQueue(status="closed")
    s = _make_supervisor(tmp_path, queue)
    _handle(s, _task(), _outcome(TaskOutcome.FAILURE, exit_code=1))
    task_dir = s.state.task_dir_for(_task().id)
    assert not (task_dir / ".failures").exists()
    assert not (task_dir / ".noclose").exists()
    assert not (task_dir / ".stalls").exists()


def test_killed_closed_bead_no_set_blocked(tmp_path: Path) -> None:
    queue = StubQueue(status="closed")
    s = _make_supervisor(tmp_path, queue)
    _handle(s, _task(), _outcome(TaskOutcome.KILLED))
    assert len(queue.blocked) == 0


def test_killed_closed_bead_no_comment(tmp_path: Path) -> None:
    queue = StubQueue(status="closed")
    s = _make_supervisor(tmp_path, queue)
    _handle(s, _task(), _outcome(TaskOutcome.KILLED))
    assert len(queue.comments) == 0


def test_success_task_still_in_progress_calls_release(tmp_path: Path) -> None:
    queue = StubQueue(status="in_progress")
    s = _make_supervisor(tmp_path, queue)
    _handle(s, _task(), _outcome(TaskOutcome.SUCCESS))
    assert len(queue.released) == 1
    assert "re-queueing" in queue.released[0][1]
    assert "#1/" in queue.released[0][1]


def test_success_task_already_closed_no_release(tmp_path: Path) -> None:
    queue = StubQueue(status="closed")
    s = _make_supervisor(tmp_path, queue)
    _handle(s, _task(), _outcome(TaskOutcome.SUCCESS))
    assert len(queue.released) == 0


def test_noclose_releases_below_limit_then_blocks(tmp_path: Path) -> None:
    queue = StubQueue(status="in_progress")
    s = _make_supervisor(tmp_path, queue)
    for _ in range(NOCLOSE_MAX_ROUNDS - 1):
        _handle(s, _task(), _outcome(TaskOutcome.SUCCESS))
    assert len(queue.released) == NOCLOSE_MAX_ROUNDS - 1
    assert len(queue.blocked) == 0
    _handle(s, _task(), _outcome(TaskOutcome.SUCCESS))
    assert len(queue.blocked) == 1
    assert "needs human review" in queue.blocked[0][1]


def test_noclose_exhausted_posts_comment(tmp_path: Path) -> None:
    queue = StubQueue(status="in_progress")
    s = _make_supervisor(tmp_path, queue)
    for _ in range(NOCLOSE_MAX_ROUNDS):
        _handle(s, _task(), _outcome(TaskOutcome.SUCCESS))
    assert len(queue.comments) >= 1
    assert any("exhausted" in c[1] for c in queue.comments)


def test_no_counter_files_created(tmp_path: Path) -> None:
    queue = StubQueue(status="in_progress")
    s = _make_supervisor(tmp_path, queue)
    _handle(s, _task(), _outcome(TaskOutcome.SUCCESS))
    task_dir = s.state.task_dir_for(_task().id)
    assert not (task_dir / ".noclose").exists()
    assert not (task_dir / ".failures").exists()


def test_blocked_by_coder_already_blocked_no_queue_writes(tmp_path: Path) -> None:
    queue = StubQueue(status="blocked")
    s = _make_supervisor(tmp_path, queue)
    _handle(s, _task(), _outcome(TaskOutcome.BLOCKED_BY_CODER))
    assert len(queue.released) == 0
    assert len(queue.blocked) == 0
    assert len(queue.comments) == 0


def test_blocked_by_coder_still_open_calls_set_blocked(tmp_path: Path) -> None:
    queue = StubQueue(status="open")
    s = _make_supervisor(tmp_path, queue)
    _handle(s, _task(), _outcome(TaskOutcome.BLOCKED_BY_CODER, reason="need creds"))
    assert queue.blocked == [("t-001", "need creds")]
