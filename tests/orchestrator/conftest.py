"""Shared fixtures and helpers for orchestrator tests."""

from __future__ import annotations

from pathlib import Path

from fleet.core.config import RuntimeConfig
from fleet.core.task import Task, TaskOutcome, TaskOutcomeRecord
from fleet.orchestrator.reap import handle_outcome
from fleet.orchestrator.supervisor import Supervisor
from fleet.state import attempts
from tests.conftest import make_running_worker, make_supervisor

# ---------------------------------------------------------------------------
# Shared by test_supervisor_failures.py splits (Clean 29/30: moved, not rewritten).
# ---------------------------------------------------------------------------


class StubQueue:
    def __init__(self, status: str = "open") -> None:
        self._status = status
        self.released: list[tuple[str, str]] = []
        self.blocked: list[tuple[str, str]] = []
        self.comments: list[tuple[str, str]] = []

    def claim_next(self, claimer_id, *, can_claim=None):
        return None

    def release(self, task_id, reason="", wait_sec=0):
        self.released.append((task_id, reason))

    def set_blocked(self, task_id, reason):
        self.blocked.append((task_id, reason))

    def close(self, task_id, reason="completed"):
        pass

    def comment(self, task_id, body):
        self.comments.append((task_id, body))

    def get(self, task_id):
        return Task(id=task_id, title="T", description=None, status=self._status)

    def list_ready(self, limit=50):
        return []

    def set_bd_fields(self, task_id: str, body: dict) -> None:
        pass


def _make_supervisor(
    tmp_path: Path, queue: StubQueue, config: RuntimeConfig | None = None
) -> Supervisor:
    return make_supervisor(tmp_path, queue=queue, config=config, services=[], checks=[])


def _handle(s: Supervisor, task: Task, record: TaskOutcomeRecord) -> None:
    """Fold one outcome through reap, opening a fresh attempt like spawn does."""
    n = attempts.record_start(
        s.state.task_dir_for(task.id), coder="c", model="m", worker="task.fresh"
    )
    worker = make_running_worker(task.id, None, task=task, attempt_n=n)
    handle_outcome(s.state, worker, record)


def _task(task_id: str = "t-001", status: str = "in_progress") -> Task:
    return Task(id=task_id, title="Test", description=None, status=status)


def _outcome(
    outcome: TaskOutcome,
    exit_code: int = 0,
    reason: str = "",
    resets_at: int | None = None,
    stderr_tail: str | None = None,
) -> TaskOutcomeRecord:
    return TaskOutcomeRecord(
        outcome=outcome,
        exit_code=exit_code,
        reason=reason,
        resets_at=resets_at,
        stderr_tail=stderr_tail,
    )


def _history_outcomes(tmp_path: Path, task_id: str = "t-001") -> list[str]:
    return [
        e.get("outcome")
        for e in attempts.load_attempts(tmp_path / "tasks" / task_id)
        if e.get("outcome")
    ]
