"""Tests for bd passthrough and create (unit under test: cli/beads.py)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from fleet.cli.main import app
from fleet.core.limits import BD_TIMEOUT_SEC
from tests.cli.conftest import runner


def _fake_create_result(task_id: str, title: str = "T") -> MagicMock:

    body = {"id": task_id, "title": title, "status": "open"}
    return MagicMock(returncode=0, stdout=json.dumps(body), stderr="")


def test_bd_passthrough_forwards_args_with_fleet_home_cwd(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    completed = MagicMock(returncode=0, stdout="", stderr="")
    with patch("fleet.beads.client.subprocess.run", return_value=completed) as mock_run:
        result = runner.invoke(app, ["bd", "ready", "--limit", "5", "--json"])
    assert result.exit_code == 0
    mock_run.assert_called_once()
    args, kwargs = mock_run.call_args
    assert args[0] == ["bd", "ready", "--limit", "5", "--json"]
    assert kwargs["cwd"] == Path(tmp_path).resolve()


def test_bd_passthrough_propagates_nonzero_exit_code(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    completed = MagicMock(returncode=2, stdout="", stderr="")
    with patch("fleet.beads.client.subprocess.run", return_value=completed):
        result = runner.invoke(app, ["bd", "show", "missing-id"])
    assert result.exit_code == 2


def test_bd_passthrough_does_not_intercept_help_flag(tmp_path, monkeypatch) -> None:
    """A `--help` after `bd` should be passed to bd, not handled by typer."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    completed = MagicMock(returncode=0, stdout="", stderr="")
    with patch("fleet.beads.client.subprocess.run", return_value=completed) as mock_run:
        runner.invoke(app, ["bd", "--help"])
    mock_run.assert_called_once()
    args, _ = mock_run.call_args
    assert args[0] == ["bd", "--help"]


def test_bd_passthrough_listed_in_help() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "bd" in result.output


def test_bd_create_captures_invocation_cwd_into_task_json(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    invocation_dir = tmp_path / "user-project"
    invocation_dir.mkdir()
    monkeypatch.chdir(invocation_dir)

    with patch(
        "fleet.beads.client.subprocess.run",
        return_value=_fake_create_result("fleet-abc", "My task"),
    ):
        result = runner.invoke(app, ["bd", "create", "My task"])

    assert result.exit_code == 0, result.output + (result.stderr or "")
    meta_path = tmp_path / "tasks" / "fleet-abc" / "task.json"
    assert meta_path.exists()
    meta = json.loads(meta_path.read_text())
    assert meta["cwd"] == str(invocation_dir)
    assert meta["id"] == "fleet-abc"


def test_bd_create_injects_json_flag_when_user_did_not_pass_it(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    with patch(
        "fleet.beads.client.subprocess.run", return_value=_fake_create_result("fleet-xyz")
    ) as mock_run:
        runner.invoke(app, ["bd", "create", "title"])
    args, _ = mock_run.call_args
    assert "--json" in args[0]


def test_bd_create_preserves_user_json_output(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    with patch(
        "fleet.beads.client.subprocess.run", return_value=_fake_create_result("fleet-xyz", "Hi")
    ):
        result = runner.invoke(app, ["bd", "create", "--json", "Hi"])
    assert result.exit_code == 0
    # When user passed --json, fleet should NOT replace bd's JSON with a human line.
    assert '"id": "fleet-xyz"' in result.output


def test_bd_create_emits_human_summary_when_no_json_requested(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    invocation_dir = tmp_path / "project-a"
    invocation_dir.mkdir()
    monkeypatch.chdir(invocation_dir)
    with patch(
        "fleet.beads.client.subprocess.run",
        return_value=_fake_create_result("fleet-q1", "Do thing"),
    ):
        result = runner.invoke(app, ["bd", "create", "Do thing"])
    assert result.exit_code == 0
    assert "fleet-q1" in result.output
    assert "Do thing" in result.output
    assert str(invocation_dir) in result.output


def test_bd_create_dry_run_does_not_write_task_json(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    with patch("fleet.beads.client.subprocess.run", return_value=_fake_create_result("fleet-dry")):
        runner.invoke(app, ["bd", "create", "--dry-run", "title"])
    meta_path = tmp_path / "tasks" / "fleet-dry" / "task.json"
    assert not meta_path.exists()


def test_bd_create_nonzero_exit_does_not_write_task_json(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    completed = MagicMock(returncode=1, stdout="", stderr="some bd error\n")
    with patch("fleet.beads.client.subprocess.run", return_value=completed):
        result = runner.invoke(app, ["bd", "create", "boom"])
    assert result.exit_code == 1
    assert not (tmp_path / "tasks").exists() or not list((tmp_path / "tasks").iterdir())


def test_bd_non_create_subcommand_uses_client_with_timeout(tmp_path, monkeypatch) -> None:
    """`bd show ...` goes through BdClient (timeout-owned), not raw subprocess."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    completed = MagicMock(returncode=0, stdout="", stderr="")
    with patch("fleet.beads.client.subprocess.run", return_value=completed) as mock_run:
        result = runner.invoke(app, ["bd", "show", "fleet-1"])
    assert result.exit_code == 0
    args, kwargs = mock_run.call_args
    assert args[0] == ["bd", "show", "fleet-1"]
    assert kwargs["timeout"] == BD_TIMEOUT_SEC


def test_bd_create_strips_coder_and_model_from_bd_args(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    with patch(
        "fleet.beads.client.subprocess.run",
        return_value=_fake_create_result("fleet-c1", "T"),
    ) as mock_run:
        result = runner.invoke(
            app,
            ["bd", "create", "--coder", "agy", "--model", "opus", "T"],
        )
    assert result.exit_code == 0, result.output
    args, _ = mock_run.call_args
    forwarded = args[0]
    assert "--coder" not in forwarded
    assert "--model" not in forwarded
    assert "agy" not in forwarded
    assert "opus" not in forwarded


def test_bd_create_persists_coder_and_model_overrides(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    with patch(
        "fleet.beads.client.subprocess.run", return_value=_fake_create_result("fleet-c2", "T")
    ):
        result = runner.invoke(
            app,
            ["bd", "create", "--coder", "agy", "--model", "opus", "T"],
        )
    assert result.exit_code == 0, result.output
    meta = json.loads((tmp_path / "tasks" / "fleet-c2" / "task.json").read_text())
    assert meta["coder"] == "agy"
    assert meta["model"] == "opus"


def test_bd_create_accepts_equals_form_for_coder(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    with patch(
        "fleet.beads.client.subprocess.run",
        return_value=_fake_create_result("fleet-c3", "T"),
    ) as mock_run:
        result = runner.invoke(app, ["bd", "create", "--coder=agy", "T"])
    assert result.exit_code == 0, result.output
    forwarded = mock_run.call_args[0][0]
    assert not any(a.startswith("--coder") for a in forwarded)
    meta = json.loads((tmp_path / "tasks" / "fleet-c3" / "task.json").read_text())
    assert meta["coder"] == "agy"


def test_bd_create_rejects_unknown_coder(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    with patch("fleet.beads.client.subprocess.run") as mock_run:
        result = runner.invoke(
            app,
            ["bd", "create", "--coder", "does-not-exist", "T"],
        )
    # bd must not be called when the coder is invalid.
    mock_run.assert_not_called()
    assert result.exit_code == 2
    assert "does-not-exist" in result.output or "Available" in result.output


def test_bd_create_without_overrides_does_not_write_them(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    with patch(
        "fleet.beads.client.subprocess.run", return_value=_fake_create_result("fleet-c4", "T")
    ):
        runner.invoke(app, ["bd", "create", "T"])
    meta = json.loads((tmp_path / "tasks" / "fleet-c4" / "task.json").read_text())
    assert "coder" not in meta or meta["coder"] is None
    assert "model" not in meta or meta["model"] is None


def test_bd_create_human_summary_includes_overrides(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    with patch(
        "fleet.beads.client.subprocess.run", return_value=_fake_create_result("fleet-c5", "Do")
    ):
        result = runner.invoke(
            app,
            ["bd", "create", "--coder", "agy", "--model", "opus", "Do"],
        )
    assert result.exit_code == 0, result.output
    assert "coder: agy" in result.output
    assert "model: opus" in result.output
