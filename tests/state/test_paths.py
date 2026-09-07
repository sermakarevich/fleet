from __future__ import annotations

from pathlib import Path

from fleet.state.paths import fleet_home, task_dir, tasks_root


def test_tasks_root_composition(tmp_path: Path) -> None:
    assert tasks_root(tmp_path) == tmp_path / "tasks"


def test_task_dir_composition(tmp_path: Path) -> None:
    assert task_dir(tmp_path, "fleet-abc") == tmp_path / "tasks" / "fleet-abc"


def test_fleet_home_env_override(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    assert fleet_home() == tmp_path


def test_fleet_home_default_is_dot_fleet(monkeypatch) -> None:
    monkeypatch.delenv("FLEET_HOME", raising=False)
    assert fleet_home() == Path.home() / ".fleet"
