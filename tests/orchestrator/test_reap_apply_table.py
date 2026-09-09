"""Tests for orchestrator/reap.py::APPLY. Mirrors the source path."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from fleet.core.clock import FakeClock
from fleet.core.retry_policy import Action, RetryDecision
from fleet.core.task import Task, TaskOutcome, TaskOutcomeRecord
from fleet.orchestrator.reap import APPLY, ReapContext, apply_decision
from tests.conftest import FakeQueue, make_supervisor


def _task(task_id: str = "t-001") -> Task:
    """An in-progress bead for the apply table tests."""
    return Task(id=task_id, title="T", description=None, status="in_progress")


def _ctx(
    task_id: str = "t-001",
    outcome: TaskOutcome = TaskOutcome.FAILURE,
    task_dir: Path = Path("/nonexistent"),
) -> ReapContext:
    """A minimal reap context for a finished worker with no declared result."""
    return ReapContext(
        task=_task(task_id),
        task_dir=task_dir,
        record=TaskOutcomeRecord(outcome=outcome, exit_code=1, reason="boom"),
        bead_status="in_progress",
        result=None,
    )


def _state(tmp_path: Path, clock: FakeClock):
    """A supervisor state with an in-memory queue and a fake clock."""
    sup = make_supervisor(tmp_path, queue=FakeQueue(tasks=[_task()]), services=[], checks=[])
    sup.state.clock = clock
    return sup.state


def test_every_action_has_a_handler() -> None:
    """The APPLY table covers every Action exactly once."""
    assert set(APPLY) == set(Action)


def test_apply_noop_writes_nothing(tmp_path: Path) -> None:
    """NOOP logs only; the queue is untouched."""
    st = _state(tmp_path, FakeClock())
    apply_decision(st, _ctx(), RetryDecision(Action.NOOP, reason="already closed"))
    assert st.queue.released == []
    assert st.queue.closed == []


def test_apply_close_closes_the_bead(tmp_path: Path) -> None:
    """CLOSE closes with the decision reason."""
    st = _state(tmp_path, FakeClock())
    apply_decision(st, _ctx(), RetryDecision(Action.CLOSE, reason="shipped"))
    assert st.queue.closed == [("t-001", "shipped")]


def test_apply_block_marks_the_bead_blocked(tmp_path: Path) -> None:
    """BLOCK marks the bead blocked with the decision reason."""
    st = _state(tmp_path, FakeClock())
    apply_decision(
        st, _ctx(outcome=TaskOutcome.TERMINAL), RetryDecision(Action.BLOCK, reason="nope")
    )
    assert st.queue.get("t-001").status == "blocked"


def test_apply_release_releases_the_bead(tmp_path: Path) -> None:
    """RELEASE hands the bead back with the decision reason."""
    st = _state(tmp_path, FakeClock())
    apply_decision(st, _ctx(), RetryDecision(Action.RELEASE, reason="retry", wait_sec=0))
    assert st.queue.released and st.queue.released[0][0] == "t-001"


def test_rate_limit_pause_uses_the_injected_clock(tmp_path: Path) -> None:
    """The claim pause anchors to st.clock.now(), not the wall clock."""
    clock = FakeClock()
    st = _state(tmp_path, clock)
    frozen = clock.now()
    apply_decision(
        st,
        _ctx(outcome=TaskOutcome.RATE_LIMIT),
        RetryDecision(Action.RELEASE, reason="rate_limit", wait_sec=300),
    )
    assert st.paused_until == frozen + timedelta(seconds=300)
