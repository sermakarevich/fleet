from __future__ import annotations

from pathlib import Path
from unittest import mock

import structlog

from fleet.core.config import RuntimeConfig
from fleet.core.task import Task, TaskOutcome, TaskOutcomeRecord
from fleet.orchestrator.supervisor import Supervisor

# ------ Test doubles (Mirror test_supervisor_failures.py) ------


class StubCoder:
    name = "stub"

    def build_argv(self, task, task_dir, plan=None):
        return ["echo"]

    def env(self, task, task_dir):
        return {}

    def normalize_event(self, raw_line):
        return None


class StubQueue:
    def __init__(self, status: str = "open") -> None:
        self._status = status
        self.released: list[tuple[str, str]] = []
        self.blocked: list[tuple[str, str]] = []
        self.comments: list[tuple[str, str]] = []

    def claim_next(self, claimer_id):
        return None

    def release(self, task_id, reason=""):
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


def _make_supervisor(
    tmp_path: Path, queue: StubQueue, config: RuntimeConfig | None = None
) -> Supervisor:
    s = Supervisor(
        coder=StubCoder(),
        queue=queue,
        runtime_toml_path=tmp_path / "runtime.toml",
        project_root=tmp_path,
        log=structlog.get_logger(),
    )
    if config is not None:
        s.config = config
    return s


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


def _create_worktree_marker(tmp_path: Path, task: Task, worktree_dir: Path) -> None:
    """Create a .worktree marker file in the task directory."""
    task_dir = tmp_path / "tasks" / task.id
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / ".worktree").write_text(str(worktree_dir))


# ====================================================
# ISOLATED + clean commit: SUCCESS => needs_validation set, NO release/blocked/noclose
# ====================================================


def test_isolated_clean_commit_sets_needs_validation(tmp_path: Path) -> None:
    """ISOLATED + clean commit: .needs_validation is set, queue release/blocked NOT called."""
    queue = StubQueue(status="in_progress")
    s = _make_supervisor(tmp_path, queue)
    task = _task()
    wt_dir = tmp_path / "worktrees" / task.id
    _create_worktree_marker(tmp_path, task, wt_dir)

    with mock.patch("fleet.orchestrator.worktree.is_committed_clean", return_value=True):
        s._handle_outcome(task, _outcome(TaskOutcome.SUCCESS))

    # .needs_validation marker should be set
    task_dir = tmp_path / "tasks" / task.id
    assert (task_dir / ".needs_validation").exists()

    # queue.release and queue.set_blocked must NOT be called
    assert queue.released == []
    assert queue.blocked == []

    # .noclose must NOT be incremented
    assert (
        not (task_dir / ".noclose").exists()
        or (task_dir / ".noclose").read_text().strip() == "0"
    )


def test_isolated_clean_commit_no_noclose_increment(tmp_path: Path) -> None:
    """ISOLATED + clean commit: noclose counter is NOT touched."""
    queue = StubQueue(status="in_progress")
    s = _make_supervisor(tmp_path, queue)
    task = _task()
    wt_dir = tmp_path / "worktrees" / task.id
    _create_worktree_marker(tmp_path, task, wt_dir)

    with mock.patch("fleet.orchestrator.worktree.is_committed_clean", return_value=True):
        s._handle_outcome(task, _outcome(TaskOutcome.SUCCESS))

    task_dir = tmp_path / "tasks" / task.id
    assert not (task_dir / ".noclose").exists()


# ====================================================
# ISOLATED + dirty: is_committed_clean=False => no .needs_validation, release called
# ====================================================


def test_isolated_dirty_no_needs_validation(tmp_path: Path) -> None:
    """ISOLATED + dirty tree: .needs_validation is NOT set, release is called."""
    queue = StubQueue(status="in_progress")
    s = _make_supervisor(tmp_path, queue)
    task = _task()
    wt_dir = tmp_path / "worktrees" / task.id
    _create_worktree_marker(tmp_path, task, wt_dir)

    with mock.patch("fleet.orchestrator.worktree.is_committed_clean", return_value=False):
        s._handle_outcome(task, _outcome(TaskOutcome.SUCCESS))

    task_dir = tmp_path / "tasks" / task.id
    assert not (task_dir / ".needs_validation").exists()

    # release is called (re-queue for retry)
    assert len(queue.released) == 1


def test_isolated_dirty_increments_noclose(tmp_path: Path) -> None:
    """ISOLATED + dirty: .noclose counter is incremented (not .needs_validation)."""
    from fleet.state.counters import noclose_count

    queue = StubQueue(status="in_progress")
    s = _make_supervisor(tmp_path, queue)
    task = _task()
    wt_dir = tmp_path / "worktrees" / task.id
    _create_worktree_marker(tmp_path, task, wt_dir)

    with mock.patch("fleet.orchestrator.worktree.is_committed_clean", return_value=False):
        s._handle_outcome(task, _outcome(TaskOutcome.SUCCESS))

    task_dir = tmp_path / "tasks" / task.id
    assert noclose_count(task_dir) == 1


# ====================================================
# ISOLATED + dirty: exhausting NOCLOSE_LIMIT => set_blocked
# ====================================================


def test_isolated_dirty_exhausts_noclose_limit(tmp_path: Path, monkeypatch) -> None:
    """ISOLATED + dirty at NOCLOSE_LIMIT: set_blocked called."""
    monkeypatch.setattr("fleet.orchestrator.reap.NOCLOSE_LIMIT", 3)  # low limit for test

    queue = StubQueue(status="in_progress")
    s = _make_supervisor(tmp_path, queue)
    task = _task()
    wt_dir = tmp_path / "worktrees" / task.id
    _create_worktree_marker(tmp_path, task, wt_dir)

    # Pre-create .noclose file so increment_noclose starts counting
    task_dir = tmp_path / "tasks" / task.id
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / ".noclose").write_text("0")

    with mock.patch("fleet.orchestrator.worktree.is_committed_clean", return_value=False):
        s._handle_outcome(task, _outcome(TaskOutcome.SUCCESS))
        s._handle_outcome(task, _outcome(TaskOutcome.SUCCESS))
        s._handle_outcome(task, _outcome(TaskOutcome.SUCCESS))

    assert len(queue.blocked) >= 1
    assert "isolated task exited without a clean commit" in queue.blocked[-1][1]


# ====================================================
# NON-isolated (no .worktree marker): existing behavior unchanged
# ====================================================


def test_non_isolated_success_still_releases(tmp_path: Path) -> None:
    """Non-isolated task: SUCCESS with bead in_progress => release (existing behavior)."""
    queue = StubQueue(status="in_progress")
    s = _make_supervisor(tmp_path, queue)
    task = _task()
    # No .worktree marker => non-isolated path

    s._handle_outcome(task, _outcome(TaskOutcome.SUCCESS))

    assert len(queue.released) == 1
    assert "re-queueing" in queue.released[0][1]

    # .needs_validation must NOT be set
    task_dir = tmp_path / "tasks" / task.id
    assert not (task_dir / ".needs_validation").exists()


def test_non_isolated_behavior_unchanged(tmp_path: Path, monkeypatch) -> None:
    """Non-isolated: releases below NOCLOSE_LIMIT, blocks at NOCLOSE_LIMIT."""
    monkeypatch.setattr("fleet.core.outcome_policy.NOCLOSE_LIMIT", 2)
    monkeypatch.setattr("fleet.orchestrator.reap.NOCLOSE_LIMIT", 2)
    queue = StubQueue(status="in_progress")
    s = _make_supervisor(tmp_path, queue)
    task = _task()
    # No .worktree marker

    s._handle_outcome(task, _outcome(TaskOutcome.SUCCESS))
    # First SUCCESS (count 1 < 2) -> one release
    assert len(queue.released) == 1
    assert "re-queueing" in queue.released[0][1]
    assert "#1/2" in queue.released[0][1]

    s._handle_outcome(task, _outcome(TaskOutcome.SUCCESS))
    # Second SUCCESS (count 2 >= 2) -> blocked, no further release
    assert len(queue.released) == 1
    assert len(queue.blocked) == 1
    assert "needs human review" in queue.blocked[0][1]
    task_dir = tmp_path / "tasks" / task.id
    assert not (task_dir / ".needs_validation").exists()


def test_non_isolated_no_worktree_marker_doesnt_interfere_with_noclose(
    tmp_path: Path, monkeypatch
) -> None:
    """Non-isolated: releases below NOCLOSE_LIMIT, blocks at NOCLOSE_LIMIT."""
    monkeypatch.setattr("fleet.core.outcome_policy.NOCLOSE_LIMIT", 2)
    monkeypatch.setattr("fleet.orchestrator.reap.NOCLOSE_LIMIT", 2)
    queue = StubQueue(status="in_progress")
    s = _make_supervisor(tmp_path, queue)
    task = _task()

    s._handle_outcome(task, _outcome(TaskOutcome.SUCCESS))
    # First SUCCESS (count 1 < 2) -> one release
    assert len(queue.released) == 1
    assert "re-queueing" in queue.released[0][1]
    assert "#1/2" in queue.released[0][1]

    s._handle_outcome(task, _outcome(TaskOutcome.SUCCESS))

    # Second SUCCESS (count 2 >= 2) -> blocked, no further release
    assert len(queue.released) == 1
    assert len(queue.blocked) == 1
    assert "needs human review" in queue.blocked[0][1]
    task_dir = tmp_path / "tasks" / task.id
    assert not (task_dir / ".needs_validation").exists()
