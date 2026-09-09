"""WAITING outcome row + observer follow-up rounds cap.

The WAITING row lives in core/retry_policy.py; the observer cap is enforced
in orchestrator/reap.py (pure counting in core/job_plan.observer_rounds),
so this file drives both through the supervisor like
tests/orchestrator/test_reap_result.py does.
"""

from __future__ import annotations

import json
from pathlib import Path

from fleet.core.config import RuntimeConfig
from fleet.core.retry_policy import WAITING_WAIT_SEC, Action, decide
from fleet.core.task import Task, TaskOutcome, TaskOutcomeRecord
from fleet.orchestrator.reap import handle_outcome
from fleet.orchestrator.supervisor import Supervisor
from fleet.state import attempts
from fleet.state import paths as state_paths
from tests.conftest import make_running_worker, make_supervisor


class StubQueue:
    def __init__(self, status: str = "in_progress") -> None:
        self._status = status
        self.released: list[tuple[str, str, int]] = []
        self.blocked: list[tuple[str, str]] = []
        self.closed: list[tuple[str, str]] = []
        self.comments: list[tuple[str, str]] = []

    def claim_next(self, claimer_id, *, can_claim=None):
        return None

    def release(self, task_id, reason="", wait_sec=0):
        self.released.append((task_id, reason, wait_sec))

    def set_blocked(self, task_id, reason):
        self.blocked.append((task_id, reason))

    def close(self, task_id, reason="completed"):
        self.closed.append((task_id, reason))

    def comment(self, task_id, body):
        self.comments.append((task_id, body))

    def get(self, task_id):
        return Task(id=task_id, title="T", description=None, status=self._status)

    def list_ready(self, limit=50):
        return []

    def set_bd_fields(self, task_id: str, body: dict) -> None:
        pass


class StubCoder:
    name = "stub"

    def build_argv(self, task, task_dir, plan=None):
        return ["echo"]

    def env(self, task, task_dir):
        return {}

    def normalize_event(self, raw_line):
        return None


def _supervisor(tmp_path: Path, queue: StubQueue) -> Supervisor:
    return make_supervisor(tmp_path, queue=queue, services=[], checks=[])


def _handle(s: Supervisor, task: Task, record: TaskOutcomeRecord) -> None:
    """Fold one outcome through reap, opening a fresh attempt like spawn does."""
    n = attempts.record_start(
        s.state.task_dir_for(task.id), coder="c", model="m", worker="task.fresh"
    )
    worker = make_running_worker(task.id, None, task=task, attempt_n=n)
    handle_outcome(s.state, worker, record)


def _task(task_id: str = "t-001", **kw) -> Task:
    return Task(id=task_id, title="Test", description=None, status="in_progress", **kw)


# ---------------------------------------------------------------------------
# WAITING row in the retry policy
# ---------------------------------------------------------------------------


def test_waiting_releases_with_delay() -> None:
    d = decide(
        TaskOutcomeRecord(outcome=TaskOutcome.WAITING, reason="1 of 2 children still running"),
        [],
        "in_progress",
        RuntimeConfig(),
    )
    assert d.action == Action.RELEASE
    assert d.wait_sec == WAITING_WAIT_SEC
    assert "1 of 2" in d.reason


def test_waiting_rows_neither_count_nor_break_streaks() -> None:
    config = RuntimeConfig()
    rec = TaskOutcomeRecord(outcome=TaskOutcome.FAILURE, exit_code=1, reason="boom")
    history = [
        {"n": 1, "outcome": "failure", "reason": "boom", "action": "release"},
        {"n": 2, "outcome": "waiting", "reason": "w", "action": "release"},
        {"n": 3, "outcome": "failure", "reason": "boom", "action": "release"},
    ]
    # Two real failures around one waiting row: round 3 -> BLOCK.
    d = decide(rec, history, "in_progress", config)
    assert d.action == Action.BLOCK


def test_waiting_reap_releases_silently(tmp_path: Path) -> None:
    queue = StubQueue(status="in_progress")
    s = _supervisor(tmp_path, queue)
    record = TaskOutcomeRecord(outcome=TaskOutcome.WAITING, reason="1 of 2 children still running")
    _handle(s, _task(), record)
    assert queue.blocked == []
    assert queue.closed == []
    assert queue.comments == []
    assert len(queue.released) == 1
    assert queue.released[0][2] == WAITING_WAIT_SEC


# ---------------------------------------------------------------------------
# Observer follow-up rounds cap
# ---------------------------------------------------------------------------


def _write_result(tmp_path: Path, task_id: str, body: dict) -> None:
    task_dir = state_paths.task_dir(tmp_path, task_id)
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / "RESULT.json").write_text(json.dumps(body), encoding="utf-8")


def _rc0() -> TaskOutcomeRecord:
    return TaskOutcomeRecord(outcome=TaskOutcome.SUCCESS, exit_code=0, reason="")


def _seed_partial_observer_rounds(tmp_path: Path, task_id: str, n: int) -> None:
    task_dir = state_paths.task_dir(tmp_path, task_id)
    for _ in range(n):
        m = attempts.record_start(task_dir, coder="c", model="m", worker="observer")
        attempts.record_end(
            task_dir, outcome="partial", exit_code=0, reason="more work", action="release", n=m
        )


def test_observer_partial_below_cap_releases(tmp_path: Path) -> None:
    _write_result(tmp_path, "t-001", {"schema": 1, "status": "partial", "summary": "more work"})
    queue = StubQueue(status="in_progress")
    s = _supervisor(tmp_path, queue)
    _handle(s, _task(type="epic"), _rc0())
    assert queue.blocked == []
    assert len(queue.released) == 1


def test_observer_partial_at_cap_blocks(tmp_path: Path) -> None:
    _write_result(tmp_path, "t-001", {"schema": 1, "status": "partial", "summary": "more work"})
    _seed_partial_observer_rounds(tmp_path, "t-001", 2)
    queue = StubQueue(status="in_progress")
    s = _supervisor(tmp_path, queue)
    _handle(s, _task(type="epic"), _rc0())
    assert queue.released == []
    assert queue.blocked == [("t-001", "observer exhausted; needs human review")]


def test_task_partial_at_same_history_still_releases(tmp_path: Path) -> None:
    # The cap only applies to observer runs: a task-family partial with two
    # prior task-family partials follows the normal 5-round ladder.
    _write_result(tmp_path, "t-001", {"schema": 1, "status": "partial", "summary": "more work"})
    task_dir = state_paths.task_dir(tmp_path, "t-001")
    for _ in range(2):
        m = attempts.record_start(task_dir, coder="c", model="m", worker="task.continue")
        attempts.record_end(
            task_dir, outcome="partial", exit_code=0, reason="more work", action="release", n=m
        )
    queue = StubQueue(status="in_progress")
    s = _supervisor(tmp_path, queue)
    _handle(s, _task(type="task"), _rc0())
    assert queue.blocked == []
    assert len(queue.released) == 1
