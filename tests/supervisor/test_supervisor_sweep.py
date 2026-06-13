"""Tests for ``Supervisor._sweep_orphan_worktrees``."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
import structlog

from fleet.supervisor import Supervisor
from fleet.failures import set_needs_validation


class StubQueue:
    def claim_next(self, claimer_id):
        return None

    def release(self, task_id, reason=""):
        pass

    def set_blocked(self, task_id, reason):
        pass

    def close(self, task_id, reason="completed"):
        pass

    def comment(self, task_id, body):
        pass

    def get(self, task_id):
        pass

    def list_ready(self, limit=50):
        return []


class StubCoder:
    name = "stub"

    def build_argv(self, task, artifact_dir):
        return ["echo"]

    def env(self, task, artifact_dir):
        return {}

    def normalize_event(self, raw_line):
        return None


def _make_supervisor(tmp_path: Path) -> Supervisor:
    return Supervisor(
        coder=StubCoder(),
        queue=StubQueue(),
        runtime_toml_path=tmp_path / "runtime.toml",
        project_root=tmp_path,
        log=structlog.get_logger(),
    )


class TestSweepOrphanWorktrees:
    def test_removes_worktree_when_orphan(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Worktree with task NOT in flight and NO .needs_validation marker is removed."""
        fleet_home = tmp_path / ".fleet"
        worktrees = fleet_home / "worktrees"
        tasks = fleet_home / "tasks"
        worktrees.mkdir(parents=True)
        tasks.mkdir(parents=True)

        orphan_dir = worktrees / "t-orphan"
        orphan_dir.mkdir()
        orphan_dir.joinpath("HEAD").write_text("orphan")

        monkeypatch.setenv("FLEET_HOME", str(fleet_home))

        s = _make_supervisor(tmp_path)
        s.in_flight = {}

        with patch("fleet.supervisor.remove_worktree") as mock_remove:
            s._sweep_orphan_worktrees()
            mock_remove.assert_called_once_with(tmp_path, "t-orphan")

    def test_skips_when_task_in_flight(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Worktree for a task in self.in_flight is NOT removed."""
        fleet_home = tmp_path / ".fleet"
        worktrees = fleet_home / "worktrees"
        tasks = fleet_home / "tasks"
        worktrees.mkdir(parents=True)
        tasks.mkdir(parents=True)

        in_flight_dir = worktrees / "t-active"
        in_flight_dir.mkdir()
        in_flight_dir.joinpath("HEAD").write_text("active")

        monkeypatch.setenv("FLEET_HOME", str(fleet_home))

        s = _make_supervisor(tmp_path)
        s.in_flight = {"t-active": object()}

        with patch("fleet.supervisor.remove_worktree") as mock_remove:
            s._sweep_orphan_worktrees()
            mock_remove.assert_not_called()

    def test_skips_when_needs_validation_marker(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Worktree with .needs_validation marker is NOT removed."""
        fleet_home = tmp_path / ".fleet"
        worktrees = fleet_home / "worktrees"
        tasks = fleet_home / "tasks"
        worktrees.mkdir(parents=True)
        tasks.mkdir(parents=True)

        marker_dir = worktrees / "t-validate"
        marker_dir.mkdir()
        marker_dir.joinpath("HEAD").write_text("validate")

        task_dir = tasks / "t-validate"
        task_dir.mkdir(parents=True)
        set_needs_validation(task_dir)

        monkeypatch.setenv("FLEET_HOME", str(fleet_home))

        s = _make_supervisor(tmp_path)
        s.in_flight = {}

        with patch("fleet.supervisor.remove_worktree") as mock_remove:
            s._sweep_orphan_worktrees()
            mock_remove.assert_not_called()

    def test_skips_non_directories(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Non-directory entries in worktrees are skipped."""
        fleet_home = tmp_path / ".fleet"
        worktrees = fleet_home / "worktrees"
        worktrees.mkdir(parents=True)

        # A regular file, not a directory
        (worktrees / "not-a-dir").write_text("file")

        monkeypatch.setenv("FLEET_HOME", str(fleet_home))

        s = _make_supervisor(tmp_path)
        s.in_flight = {}

        with patch("fleet.supervisor.remove_worktree") as mock_remove:
            s._sweep_orphan_worktrees()
            mock_remove.assert_not_called()

    def test_noop_when_worktrees_dir_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Return early when the worktrees directory doesn't exist."""
        fleet_home = tmp_path / ".fleet"
        # DON'T create the worktrees directory

        monkeypatch.setenv("FLEET_HOME", str(fleet_home))

        s = _make_supervisor(tmp_path)
        s.in_flight = {}

        with patch("fleet.supervisor.remove_worktree") as mock_remove:
            s._sweep_orphan_worktrees()
            mock_remove.assert_not_called()

    def test_multiple_orphans_all_removed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Multiple orphan worktrees are all removed."""
        fleet_home = tmp_path / ".fleet"
        worktrees = fleet_home / "worktrees"
        tasks = fleet_home / "tasks"
        worktrees.mkdir(parents=True)
        tasks.mkdir(parents=True)

        for tid in ["t-a", "t-b", "t-c"]:
            (worktrees / tid).mkdir()

        monkeypatch.setenv("FLEET_HOME", str(fleet_home))

        s = _make_supervisor(tmp_path)
        s.in_flight = {}

        with patch("fleet.supervisor.remove_worktree") as mock_remove:
            s._sweep_orphan_worktrees()
            removed = {call[0][1] for call in mock_remove.call_args_list}
            assert removed == {"t-a", "t-b", "t-c"}
