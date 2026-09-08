from __future__ import annotations

import json
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
        self.closed: list[tuple[str, str]] = []

    def claim_next(self, claimer_id):
        return None

    def release(self, task_id, reason="", wait_sec=0):
        self.released.append((task_id, reason))

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

    def clear_isolation_info(self, task_id):
        pass


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


def _isolate(tmp_path: Path, task: Task, base_ref: str = "main") -> Path:
    """Write task.json isolation info + a RESULT done declaration."""
    task_dir = tmp_path / "tasks" / task.id
    task_dir.mkdir(parents=True, exist_ok=True)
    wt_dir = tmp_path / "worktrees" / f"repo-{task.id}"
    wt_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / "task.json").write_text(
        json.dumps(
            {
                "id": task.id,
                "repo_root": str(tmp_path),
                "base_ref": base_ref,
                "worktree_path": str(wt_dir),
            }
        )
    )
    artifacts = task_dir / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    (artifacts / "RESULT.json").write_text(
        json.dumps({"schema": 1, "status": "done", "summary": "did it"})
    )
    return wt_dir


# ====================================================
# ISOLATED + RESULT done + clean commit => needs_validation, NO release/blocked
# ====================================================


def test_isolated_clean_commit_sets_needs_validation(tmp_path: Path) -> None:
    """ISOLATED + RESULT done + clean: .needs_validation set, no release/block."""
    queue = StubQueue(status="in_progress")
    s = _make_supervisor(tmp_path, queue)
    task = _task()
    _isolate(tmp_path, task)

    with mock.patch("fleet.orchestrator.worktree.is_committed_clean", return_value=True):
        s._handle_outcome(task, _outcome(TaskOutcome.SUCCESS))

    task_dir = tmp_path / "tasks" / task.id
    assert (task_dir / ".needs_validation").exists()
    assert queue.released == []
    assert queue.blocked == []
    assert not (task_dir / ".noclose").exists()
    assert not (task_dir / ".failures").exists()


def test_isolated_clean_commit_no_noclose_increment(tmp_path: Path) -> None:
    """ISOLATED + RESULT done + clean: noclose counter is NOT touched."""
    queue = StubQueue(status="in_progress")
    s = _make_supervisor(tmp_path, queue)
    task = _task()
    _isolate(tmp_path, task)

    with mock.patch("fleet.orchestrator.worktree.is_committed_clean", return_value=True):
        s._handle_outcome(task, _outcome(TaskOutcome.SUCCESS))

    task_dir = tmp_path / "tasks" / task.id
    assert not (task_dir / ".noclose").exists()


def test_isolated_clean_but_no_result_falls_through(tmp_path: Path) -> None:
    """ISOLATED + clean but no RESULT.json: normal noclose path (release)."""
    queue = StubQueue(status="in_progress")
    s = _make_supervisor(tmp_path, queue)
    task = _task()
    wt_dir = _isolate(tmp_path, task)
    # Remove the RESULT declaration -> SUCCESS without RESULT.
    (tmp_path / "tasks" / task.id / "artifacts" / "RESULT.json").unlink()

    with mock.patch("fleet.orchestrator.worktree.is_committed_clean", return_value=True):
        s._handle_outcome(task, _outcome(TaskOutcome.SUCCESS))

    task_dir = tmp_path / "tasks" / task.id
    assert not (task_dir / ".needs_validation").exists()
    assert len(queue.released) == 1
    assert wt_dir.exists()


# ====================================================
# ISOLATED + dirty: is_committed_clean=False => no .needs_validation, release called
# ====================================================


def test_isolated_dirty_no_needs_validation(tmp_path: Path) -> None:
    """ISOLATED + RESULT done + dirty tree: NOT validated, released."""
    queue = StubQueue(status="in_progress")
    s = _make_supervisor(tmp_path, queue)
    task = _task()
    _isolate(tmp_path, task)

    with mock.patch("fleet.orchestrator.worktree.is_committed_clean", return_value=False):
        s._handle_outcome(task, _outcome(TaskOutcome.SUCCESS))

    task_dir = tmp_path / "tasks" / task.id
    assert not (task_dir / ".needs_validation").exists()
    assert len(queue.released) == 1


def test_isolated_dirty_journals_history(tmp_path: Path) -> None:
    """ISOLATED + dirty: attempt journaled, no counter files."""
    from fleet.state.attempts import load_attempts

    queue = StubQueue(status="in_progress")
    s = _make_supervisor(tmp_path, queue)
    task = _task()
    _isolate(tmp_path, task)

    with mock.patch("fleet.orchestrator.worktree.is_committed_clean", return_value=False):
        s._handle_outcome(task, _outcome(TaskOutcome.SUCCESS))

    task_dir = tmp_path / "tasks" / task.id
    assert not (task_dir / ".noclose").exists()
    assert [e.get("outcome") for e in load_attempts(task_dir) if e.get("outcome")] == ["success"]


# ====================================================
# ISOLATED + dirty: exhausting NOCLOSE_MAX_ROUNDS => set_blocked
# ====================================================


def test_isolated_dirty_exhausts_noclose_limit(tmp_path: Path) -> None:
    """ISOLATED + dirty at the noclose max rounds (3): set_blocked called."""
    queue = StubQueue(status="in_progress")
    s = _make_supervisor(tmp_path, queue)
    task = _task()
    _isolate(tmp_path, task)

    with mock.patch("fleet.orchestrator.worktree.is_committed_clean", return_value=False):
        s._handle_outcome(task, _outcome(TaskOutcome.SUCCESS))
        s._handle_outcome(task, _outcome(TaskOutcome.SUCCESS))
        s._handle_outcome(task, _outcome(TaskOutcome.SUCCESS))

    assert len(queue.blocked) >= 1
    assert "isolated task exited without a clean commit" in queue.blocked[-1][1]


# ====================================================
# NON-isolated (no task.json info): existing behavior unchanged
# ====================================================


def test_non_isolated_success_still_releases(tmp_path: Path) -> None:
    """Non-isolated task: SUCCESS with bead in_progress => release (existing behavior)."""
    queue = StubQueue(status="in_progress")
    s = _make_supervisor(tmp_path, queue)
    task = _task()
    # No task.json isolation info => non-isolated path

    s._handle_outcome(task, _outcome(TaskOutcome.SUCCESS))

    assert len(queue.released) == 1
    assert "re-queueing" in queue.released[0][1]

    task_dir = tmp_path / "tasks" / task.id
    assert not (task_dir / ".needs_validation").exists()


def test_non_isolated_behavior_unchanged(tmp_path: Path) -> None:
    """Non-isolated: releases below the noclose max (3), blocks at 3."""
    queue = StubQueue(status="in_progress")
    s = _make_supervisor(tmp_path, queue)
    task = _task()

    s._handle_outcome(task, _outcome(TaskOutcome.SUCCESS))
    assert len(queue.released) == 1
    assert "re-queueing" in queue.released[0][1]
    assert "#1/3" in queue.released[0][1]

    s._handle_outcome(task, _outcome(TaskOutcome.SUCCESS))
    assert len(queue.released) == 2
    assert len(queue.blocked) == 0

    s._handle_outcome(task, _outcome(TaskOutcome.SUCCESS))
    assert len(queue.released) == 2
    assert len(queue.blocked) == 1
    assert "needs human review" in queue.blocked[0][1]
    task_dir = tmp_path / "tasks" / task.id
    assert not (task_dir / ".needs_validation").exists()


def test_non_isolated_no_worktree_marker_doesnt_interfere_with_noclose(
    tmp_path: Path,
) -> None:
    """Non-isolated: releases below the noclose max (3), blocks at 3."""
    queue = StubQueue(status="in_progress")
    s = _make_supervisor(tmp_path, queue)
    task = _task()

    s._handle_outcome(task, _outcome(TaskOutcome.SUCCESS))
    assert len(queue.released) == 1
    assert "re-queueing" in queue.released[0][1]
    assert "#1/3" in queue.released[0][1]

    s._handle_outcome(task, _outcome(TaskOutcome.SUCCESS))
    s._handle_outcome(task, _outcome(TaskOutcome.SUCCESS))

    assert len(queue.released) == 2
    assert len(queue.blocked) == 1
    assert "needs human review" in queue.blocked[0][1]
    task_dir = tmp_path / "tasks" / task.id
    assert not (task_dir / ".needs_validation").exists()


# ====================================================
# ISOLATED + RESULT done + clean worktree with NO commits: a commit is not
# required; the task closes like a plain "done" and the worktree is dropped.
# ====================================================


def test_isolated_clean_without_commits_closes_without_requiring_commit(
    tmp_path: Path,
) -> None:
    """Regression: a knowledge-base task that touched nothing in the repo was
    blocked after three rounds of "exited without a clean commit"."""
    queue = StubQueue(status="in_progress")
    s = _make_supervisor(tmp_path, queue)
    task = _task()
    _isolate(tmp_path, task)

    with (
        mock.patch("fleet.orchestrator.worktree.is_committed_clean", return_value=False),
        mock.patch("fleet.orchestrator.worktree.has_uncommitted_changes", return_value=False),
        mock.patch("fleet.orchestrator.worktree.cleanup_worktree") as cleanup,
    ):
        s._handle_outcome(task, _outcome(TaskOutcome.SUCCESS))

    task_dir = tmp_path / "tasks" / task.id
    assert queue.closed and queue.closed[0][0] == task.id
    assert queue.released == []
    assert queue.blocked == []
    assert not (task_dir / ".needs_validation").exists()
    assert cleanup.called


def test_isolated_uncommitted_changes_still_ask_for_a_commit(tmp_path: Path) -> None:
    """Leftover uncommitted changes are the one case that keeps the retry rounds."""
    queue = StubQueue(status="in_progress")
    s = _make_supervisor(tmp_path, queue)
    task = _task()
    _isolate(tmp_path, task)

    with (
        mock.patch("fleet.orchestrator.worktree.is_committed_clean", return_value=False),
        mock.patch("fleet.orchestrator.worktree.has_uncommitted_changes", return_value=True),
    ):
        s._handle_outcome(task, _outcome(TaskOutcome.SUCCESS))

    assert queue.closed == []
    assert len(queue.released) == 1
    assert "uncommitted changes" in queue.released[0][1]

