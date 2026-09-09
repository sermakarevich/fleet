"""Tests for the one CLI error path: ExitCode values and fail()."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import typer
from typer.testing import CliRunner

from fleet.beads.client import BdError
from fleet.cli.errors import ExitCode, fail
from fleet.cli.main import app

runner = CliRunner()


def test_exit_codes_match_spec() -> None:
    assert (ExitCode.OK, ExitCode.ERROR, ExitCode.USAGE, ExitCode.NOT_FOUND, ExitCode.BACKEND) == (
        0,
        1,
        2,
        3,
        4,
    )


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        (ExitCode.ERROR, 1),
        (ExitCode.USAGE, 2),
        (ExitCode.NOT_FOUND, 3),
        (ExitCode.BACKEND, 4),
    ],
)
def test_fail_exits_with_given_code(code: ExitCode, expected: int, capsys) -> None:
    with pytest.raises(typer.Exit) as exc_info:
        fail("boom", code)
    assert exc_info.value.exit_code == expected
    assert "Error: boom" in capsys.readouterr().err


def test_fail_defaults_to_error(capsys) -> None:
    with pytest.raises(typer.Exit) as exc_info:
        fail("boom")
    assert exc_info.value.exit_code == 1
    assert "Error: boom" in capsys.readouterr().err


def test_fail_does_not_double_error_prefix(capsys) -> None:
    with pytest.raises(typer.Exit):
        fail("Error: already prefixed")
    assert "Error: Error:" not in capsys.readouterr().err


def test_show_missing_task_is_not_found() -> None:
    with patch("fleet.cli.bootstrap.BeadsQueue") as mock_cls:
        mock_q = MagicMock()
        mock_cls.return_value = mock_q
        mock_q.get.side_effect = BdError("task not found: nope")
        result = runner.invoke(app, ["show", "nope"])
    assert result.exit_code == int(ExitCode.NOT_FOUND)


def test_kill_missing_task_json_is_not_found(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    (tmp_path / "tasks" / "t-x").mkdir(parents=True)
    result = runner.invoke(app, ["kill", "t-x"])
    assert result.exit_code == int(ExitCode.NOT_FOUND)


def test_tasks_backend_failure_is_backend() -> None:
    with patch("fleet.cli.bootstrap.BeadsQueue") as mock_cls:
        mock_q = MagicMock()
        mock_cls.return_value = mock_q
        mock_q.list_in_progress.side_effect = BdError("bd exploded")
        result = runner.invoke(app, ["tasks"])
    assert result.exit_code == int(ExitCode.BACKEND)


def test_log_non_positive_tail_is_usage(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    log_dir = tmp_path / "logging"
    log_dir.mkdir()
    (log_dir / "fleet-2026-05-23.jsonl").write_text("x\n", encoding="utf-8")
    result = runner.invoke(app, ["log", "0"])
    assert result.exit_code == int(ExitCode.USAGE)


def test_config_set_malformed_pair_is_usage(tmp_path: Path) -> None:
    with patch("fleet.cli.config.fleet_home", return_value=tmp_path):
        result = runner.invoke(app, ["config", "set", "not-a-pair"])
    assert result.exit_code == int(ExitCode.USAGE)


def test_bd_create_unknown_coder_is_usage(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    with patch("fleet.beads.client.subprocess.run") as mock_run:
        result = runner.invoke(app, ["bd", "create", "--coder", "nope", "T"])
    mock_run.assert_not_called()
    assert result.exit_code == int(ExitCode.USAGE)


def test_bd_passthrough_timeout_is_backend(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    with patch(
        "fleet.beads.client.subprocess.run",
        side_effect=BdError("bd show timed out after 30s"),
    ):
        result = runner.invoke(app, ["bd", "show", "fleet-1"])
    assert result.exit_code == int(ExitCode.BACKEND)
