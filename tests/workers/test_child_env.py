"""Tests for workers/child_env.py: the one child-env builder. Mirrors the source path."""

from pathlib import Path

from fleet.core.task import Task
from fleet.workers.child_env import child_env


class _Coder:
    def __init__(self, overlay: dict[str, str] | None = None) -> None:
        self._overlay = overlay or {}

    def env(self, task: Task, task_dir: Path) -> dict[str, str]:
        return {
            "FLEET_TASK_ID": task.id,
            "FLEET_TASK_DIR": str(task_dir),
            **self._overlay,
        }


def _task() -> Task:
    return Task(id="t-1", title="T", description=None, status="in_progress")


def test_layers_base_coder_and_attempt(tmp_path: Path) -> None:
    """Base env survives, coder overlay wins, attempt facts are added."""
    task_dir = tmp_path / "tasks" / "t-1"
    attempt_dir = task_dir / "attempts" / "3"
    base = {"PATH": "/bin", "FLEET_TASK_ID": "stale"}

    env = child_env(
        _Coder(),
        _task(),
        task_dir,
        attempt_dir,
        base_env=base,
        attempt_n=3,
        launch_mode="fresh",
        fleet_home=tmp_path,
    )

    assert env["PATH"] == "/bin"
    assert env["FLEET_TASK_ID"] == "t-1"
    assert env["FLEET_TASK_DIR"] == str(task_dir)
    assert env["FLEET_ATTEMPT_DIR"] == str(attempt_dir)
    assert env["FLEET_ATTEMPT_N"] == "3"
    assert env["FLEET_LAUNCH_MODE"] == "fresh"
    assert env["BEADS_DIR"] == str(tmp_path / ".beads")


def test_coder_beads_dir_wins_over_default(tmp_path: Path) -> None:
    """An explicit BEADS_DIR from the coder or base env is never overridden."""
    env = child_env(
        _Coder({"BEADS_DIR": "/custom/.beads"}),
        _task(),
        tmp_path,
        tmp_path / "attempts" / "1",
        base_env={},
        fleet_home=tmp_path,
    )
    assert env["BEADS_DIR"] == "/custom/.beads"


def test_minimal_call_adds_attempt_dir_only(tmp_path: Path) -> None:
    """Compact's minimal call still tags the attempt dir without extras."""
    env = child_env(_Coder(), _task(), tmp_path, tmp_path / "attempts" / "7", base_env={})

    assert env["FLEET_ATTEMPT_DIR"] == str(tmp_path / "attempts" / "7")
    assert "FLEET_ATTEMPT_N" not in env
    assert "FLEET_LAUNCH_MODE" not in env
    assert "BEADS_DIR" not in env


def test_base_env_is_not_mutated(tmp_path: Path) -> None:
    """The builder copies: callers' dicts never gain FLEET_* keys."""
    base = {"PATH": "/bin"}
    child_env(_Coder(), _task(), tmp_path, tmp_path, base_env=base, attempt_n=1)

    assert base == {"PATH": "/bin"}
