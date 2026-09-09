"""Tests for ``orchestrator.leases::sweep_orphan_worktrees``."""

from __future__ import annotations

import json
from pathlib import Path

from fleet.orchestrator.leases import _remove_orphan_dir, sweep_orphan_worktrees
from fleet.orchestrator.supervisor import Supervisor
from fleet.state.validation_marker import set_needs_validation
from tests.conftest import make_running_worker, make_supervisor


def _make_supervisor(fleet_home: Path) -> Supervisor:
    return make_supervisor(fleet_home, services=[], checks=[])


def _fleet_home(tmp_path: Path) -> Path:
    fleet_home = tmp_path / ".fleet"
    (fleet_home / "worktrees").mkdir(parents=True)
    (fleet_home / "tasks").mkdir(parents=True)
    return fleet_home


class TestSweepOrphanWorktrees:
    def test_removes_worktree_when_orphan(self, tmp_path: Path) -> None:
        """Worktree with no task.json ref and no validation marker is removed."""
        fleet_home = _fleet_home(tmp_path)
        orphan_dir = fleet_home / "worktrees" / "repo-t-orphan"
        orphan_dir.mkdir()
        orphan_dir.joinpath("HEAD").write_text("orphan")

        s = _make_supervisor(fleet_home)

        sweep_orphan_worktrees(s.state)
        assert not orphan_dir.exists()

    def test_skips_when_task_in_flight(self, tmp_path: Path) -> None:
        """Worktree for a task in state.running is NOT removed."""
        fleet_home = _fleet_home(tmp_path)
        active = fleet_home / "worktrees" / "repo-t-active"
        active.mkdir()

        s = _make_supervisor(fleet_home)
        s.state.running["t-active"] = make_running_worker("t-active", tmp_path)

        sweep_orphan_worktrees(s.state)
        assert active.exists()

    def test_skips_when_needs_validation_marker(self, tmp_path: Path) -> None:
        """Worktree with .needs_validation marker is NOT removed."""
        fleet_home = _fleet_home(tmp_path)
        (fleet_home / "worktrees" / "repo-t-validate").mkdir()

        task_dir = fleet_home / "tasks" / "t-validate"
        task_dir.mkdir(parents=True)
        set_needs_validation(task_dir)

        s = _make_supervisor(fleet_home)

        sweep_orphan_worktrees(s.state)
        assert (fleet_home / "worktrees" / "repo-t-validate").exists()

    def test_skips_live_task_json_ref(self, tmp_path: Path) -> None:
        """Worktree still referenced by a task.json worktree_path is kept."""
        fleet_home = _fleet_home(tmp_path)
        wt = fleet_home / "worktrees" / "repo-t-live"
        wt.mkdir()
        task_dir = fleet_home / "tasks" / "t-live"
        task_dir.mkdir(parents=True)
        (task_dir / "task.json").write_text(
            json.dumps(
                {"id": "t-live", "repo_root": "/r", "base_ref": "main", "worktree_path": str(wt)}
            )
        )

        s = _make_supervisor(fleet_home)

        sweep_orphan_worktrees(s.state)
        assert wt.exists()

    def test_skips_non_directories(self, tmp_path: Path) -> None:
        """Non-directory entries in worktrees are skipped."""
        fleet_home = _fleet_home(tmp_path)
        (fleet_home / "worktrees" / "not-a-dir").write_text("file")

        s = _make_supervisor(fleet_home)

        sweep_orphan_worktrees(s.state)
        assert (fleet_home / "worktrees" / "not-a-dir").exists()

    def test_noop_when_worktrees_dir_missing(self, tmp_path: Path) -> None:
        """Return early when the worktrees directory doesn't exist."""
        fleet_home = tmp_path / ".fleet"

        s = _make_supervisor(fleet_home)

        sweep_orphan_worktrees(s.state)
        pass  # returns early; nothing to remove

    def test_multiple_orphans_all_removed(self, tmp_path: Path) -> None:
        """Multiple orphan worktrees are all removed."""
        fleet_home = _fleet_home(tmp_path)
        for tid in ["t-a", "t-b", "t-c"]:
            (fleet_home / "worktrees" / f"repo-{tid}").mkdir()

        s = _make_supervisor(fleet_home)

        sweep_orphan_worktrees(s.state)
        for tid in ["t-a", "t-b", "t-c"]:
            assert not (fleet_home / "worktrees" / f"repo-{tid}").exists()


class TestRemoveOrphanDir:
    def test_falls_back_to_rmtree(self, tmp_path: Path) -> None:
        """A dir that is not a git worktree is deleted recursively."""

        target = tmp_path / "orphan"
        target.mkdir()
        (target / "f.txt").write_text("x")
        _remove_orphan_dir(target)
        assert not target.exists()

    def test_never_raises(self, tmp_path: Path) -> None:

        _remove_orphan_dir(tmp_path / "does-not-exist")
