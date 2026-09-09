"""Tests for fleet path helpers (unit under test: state/paths.py)."""

from __future__ import annotations

from pathlib import Path

from fleet.state.paths import (
    OUTPUTS_DIR,
    OUTPUTS_JSON,
    PROMPT_MD,
    RESULT_JSON,
    STATE_MD,
    fleet_home,
    outputs_dir,
    outputs_file,
    prompt_file,
    read_outputs,
    result_file,
    state_file,
    task_dir,
    tasks_root,
)


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


def test_task_file_names(tmp_path: Path) -> None:
    assert STATE_MD == "STATE.md"
    assert RESULT_JSON == "RESULT.json"
    assert PROMPT_MD == "prompt.md"
    assert OUTPUTS_DIR == "outputs"
    assert OUTPUTS_JSON == "outputs.json"


def test_task_file_helpers(tmp_path: Path) -> None:
    root = task_dir(tmp_path, "fleet-abc")
    assert state_file(root) == root / "STATE.md"
    assert result_file(root) == root / "RESULT.json"
    assert outputs_dir(root) == root / "outputs"
    assert outputs_file(root) == root / "outputs.json"
    assert prompt_file(root / "attempts" / "1") == root / "attempts" / "1" / "prompt.md"


def test_read_outputs_round_trip(tmp_path: Path) -> None:
    root = task_dir(tmp_path, "fleet-abc")
    root.mkdir(parents=True)
    (root / "outputs.json").write_text('{"paper_dir": "/tmp/x", "n": 3}', encoding="utf-8")
    assert read_outputs(root) == {"paper_dir": "/tmp/x", "n": "3"}


def test_read_outputs_missing_file_is_empty(tmp_path: Path) -> None:
    root = task_dir(tmp_path, "fleet-abc")
    root.mkdir(parents=True)
    assert read_outputs(root) == {}


def test_read_outputs_invalid_file_is_empty(tmp_path: Path) -> None:
    root = task_dir(tmp_path, "fleet-abc")
    root.mkdir(parents=True)
    (root / "outputs.json").write_text("not json", encoding="utf-8")
    assert read_outputs(root) == {}
    (root / "outputs.json").write_text("[1, 2]", encoding="utf-8")
    assert read_outputs(root) == {}
