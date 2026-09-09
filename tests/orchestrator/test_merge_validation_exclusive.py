"""Exclusivity of merge validation: two supervisors, one marker, one outcome.

Regression tests for fleet-xozkr: a duplicate supervisor re-blocked a bead
that another supervisor had just validated and merged, because the second
validator saw the already-cleaned worktree and called set_blocked. Exactly
one validator may own a marker (``.validating`` lock), and a closed bead is
never set back to blocked.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import time
from pathlib import Path

from fleet.core.task import Task
from fleet.orchestrator import worktree
from fleet.orchestrator.merge_validation import MergeValidation, validate_one
from fleet.state.validation_marker import VALIDATING_STALE_SEC, validation_lock_path
from tests.conftest import make_supervisor


class StubQueue:
    """Minimal queue fake: fixed bead status plus call records."""

    def __init__(self, status: str = "in_progress") -> None:
        self._status = status
        self.released: list[tuple[str, str]] = []
        self.closed: list[tuple[str, str]] = []
        self.blocked: list[tuple[str, str]] = []

    def release(self, task_id: str, reason: str = "", wait_sec: int = 0) -> None:
        self.released.append((task_id, reason))

    def set_blocked(self, task_id: str, reason: str) -> None:
        self.blocked.append((task_id, reason))

    def close(self, task_id: str, reason: str = "completed") -> None:
        self.closed.append((task_id, reason))

    def get(self, task_id: str) -> Task:
        return Task(id=task_id, title="T", description=None, status=self._status)

    def list_ready(self, limit: int = 50) -> list[Task]:
        return []

    def clear_isolation_info(self, task_id: str) -> None:
        pass


def _make_state(tmp_path: Path, queue: StubQueue):
    sup = make_supervisor(tmp_path, queue=queue, services=[], checks=[])
    sup.state.fleet_home = tmp_path / ".fleet"
    return sup.state


def _git(path: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(path), *args], capture_output=True, check=True)


def _git_init(path: Path) -> None:
    subprocess.run(["git", "init", "-b", "main"], cwd=path, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"], cwd=path, capture_output=True, check=False
    )
    subprocess.run(
        ["git", "config", "user.name", "test"], cwd=path, capture_output=True, check=False
    )
    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", "init"],
        cwd=path,
        capture_output=True,
        check=True,
    )


def _commit(path: Path, name: str, content: str) -> None:
    (Path(path) / name).write_text(content)
    _git(path, "add", name)
    _git(
        path,
        "-c",
        "user.email=test@test.com",
        "-c",
        "user.name=test",
        "commit",
        "-m",
        "wip",
    )


def _setup_repo(tmp_path: Path) -> tuple[Path, Path]:
    fleet_home = tmp_path / ".fleet"
    fleet_home.mkdir(exist_ok=True)
    repo = tmp_path / "repo"
    repo.mkdir(exist_ok=True)
    if not (repo / ".git").exists():
        _git_init(repo)
    return fleet_home, repo


def _isolate(fleet_home: Path, repo: Path, task_id: str) -> tuple[Path, Path]:
    """Task dir with marker + isolation info; returns (task_dir, worktree)."""
    task_dir = fleet_home / "tasks" / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / ".needs_validation").write_text("1")
    wt = worktree.create_worktree(repo, task_id, base_ref="main", fleet_home=fleet_home)
    (task_dir / "task.json").write_text(
        json.dumps(
            {
                "id": task_id,
                "repo_root": str(repo),
                "base_ref": "main",
                "worktree_path": str(wt),
            }
        )
    )
    return task_dir, wt


def _run(st) -> None:
    asyncio.run(MergeValidation().tick(st))


class TestConcurrentValidators:
    def test_two_validators_one_marker_single_merge_no_block(self, tmp_path: Path):
        """Two supervisors racing one marker: exactly one merge, zero blocked."""
        fleet_home, repo = _setup_repo(tmp_path)
        task_id = "test-race-1"
        task_dir, wt = _isolate(fleet_home, repo, task_id)
        _commit(wt, "feature.txt", "feature content")

        queue = StubQueue(status="in_progress")
        st = _make_state(tmp_path, queue)

        async def _both() -> None:
            await asyncio.gather(
                validate_one(st, task_dir, task_id),
                validate_one(st, task_dir, task_id),
            )

        asyncio.run(_both())

        assert len(queue.closed) == 1
        assert queue.blocked == []
        assert (repo / "feature.txt").read_text() == "feature content"
        assert not (task_dir / ".needs_validation").exists()

    def test_loser_while_winner_holds_lock_touches_nothing(self, tmp_path: Path):
        """A validator that loses the lock leaves marker and bead alone."""
        fleet_home, repo = _setup_repo(tmp_path)
        task_id = "test-race-2"
        task_dir, wt = _isolate(fleet_home, repo, task_id)
        _commit(wt, "feature.txt", "feature content")

        queue = StubQueue(status="in_progress")
        st = _make_state(tmp_path, queue)
        # Simulate the winner: hold the lock without doing any work.
        fd = os.open(validation_lock_path(task_dir), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        try:
            _run(st)
        finally:
            os.close(fd)
            validation_lock_path(task_dir).unlink(missing_ok=True)

        assert queue.closed == []
        assert queue.blocked == []
        assert (task_dir / ".needs_validation").exists()

    def test_stale_lock_is_cleared_and_validation_proceeds(self, tmp_path: Path):
        """A crashed validator's leftover lock never wedges the marker."""
        fleet_home, repo = _setup_repo(tmp_path)
        task_id = "test-race-3"
        task_dir, wt = _isolate(fleet_home, repo, task_id)
        _commit(wt, "feature.txt", "feature content")

        fd = os.open(validation_lock_path(task_dir), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)  # crash: fd closed, lock file left behind
        old = time.time() - (VALIDATING_STALE_SEC + 60)
        os.utime(validation_lock_path(task_dir), (old, old))

        queue = StubQueue(status="in_progress")
        _run(_make_state(tmp_path, queue))

        assert len(queue.closed) == 1
        assert queue.blocked == []
        assert not validation_lock_path(task_dir).exists()


class TestClosedBeadNeverBlocked:
    def test_closed_bead_with_missing_info_is_not_blocked(self, tmp_path: Path):
        """Marker present but bead already closed: skip, never set_blocked."""
        fleet_home, _ = _setup_repo(tmp_path)
        task_id = "test-closed-1"
        task_dir = fleet_home / "tasks" / task_id
        task_dir.mkdir(parents=True, exist_ok=True)
        (task_dir / ".needs_validation").write_text("1")
        # No task.json: the old code called set_blocked here.

        queue = StubQueue(status="closed")
        _run(_make_state(tmp_path, queue))

        assert queue.blocked == []
        assert queue.closed == []
        assert not (task_dir / ".needs_validation").exists()

    def test_closed_bead_with_gone_worktree_is_not_blocked(self, tmp_path: Path):
        """The fleet-xozkr shape: merged+cleaned, then a second validator."""
        fleet_home, repo = _setup_repo(tmp_path)
        task_id = "test-closed-2"
        task_dir, wt = _isolate(fleet_home, repo, task_id)
        _commit(wt, "feature.txt", "feature content")

        queue = StubQueue(status="in_progress")
        st = _make_state(tmp_path, queue)
        _run(st)  # first supervisor merges and closes
        assert len(queue.closed) == 1

        # Marker re-appears (stale) while the bead reads closed and the
        # worktree is already cleaned up: must not re-block.
        (task_dir / ".needs_validation").write_text("1")
        queue._status = "closed"
        _run(st)

        assert len(queue.closed) == 1
        assert queue.blocked == []
