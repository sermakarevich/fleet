"""TDD tests for `fleet bd create --cwd <path>` flag (FR-21, FR-22, FR-23)."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, call, patch

import pytest
from typer.testing import CliRunner

from fleet.cli import app


BD_CREATE_JSON_RESPONSE = json.dumps(
    {"data": [{"id": "task-abc", "title": "Test Task"}]}
)


def _make_completed_process(stdout: str = BD_CREATE_JSON_RESPONSE, returncode: int = 0) -> MagicMock:
    proc = MagicMock()
    proc.stdout = stdout
    proc.stderr = ""
    proc.returncode = returncode
    return proc


@patch("fleet.cli.BeadsQueue")
@patch("fleet.cli.subprocess.run")
def test_cwd_flag_overrides_getcwd(mock_run: MagicMock, mock_queue_cls: MagicMock) -> None:
    """--cwd /custom/path uses the supplied path, not os.getcwd()."""
    mock_run.return_value = _make_completed_process()
    mock_queue = MagicMock()
    mock_queue_cls.return_value = mock_queue

    runner = CliRunner()
    result = runner.invoke(app, ["bd", "create", "Test Task", "--cwd", "/custom/path"])

    assert result.exit_code == 0, result.output
    mock_queue.set_cwd.assert_called_once_with("task-abc", "/custom/path")


@patch("fleet.cli.BeadsQueue")
@patch("fleet.cli.subprocess.run")
@patch("fleet.cli.os.getcwd", return_value="/current/dir")
def test_no_cwd_flag_falls_back_to_getcwd(
    mock_getcwd: MagicMock,
    mock_run: MagicMock,
    mock_queue_cls: MagicMock,
) -> None:
    """Without --cwd, os.getcwd() is used (existing behaviour preserved)."""
    mock_run.return_value = _make_completed_process()
    mock_queue = MagicMock()
    mock_queue_cls.return_value = mock_queue

    runner = CliRunner()
    result = runner.invoke(app, ["bd", "create", "Test Task"])

    assert result.exit_code == 0, result.output
    mock_queue.set_cwd.assert_called_once_with("task-abc", "/current/dir")


@patch("fleet.cli.BeadsQueue")
@patch("fleet.cli.subprocess.run")
def test_cwd_flag_not_forwarded_to_bd(mock_run: MagicMock, mock_queue_cls: MagicMock) -> None:
    """--cwd must be stripped from args forwarded to bd."""
    mock_run.return_value = _make_completed_process()
    mock_queue_cls.return_value = MagicMock()

    runner = CliRunner()
    runner.invoke(app, ["bd", "create", "Test Task", "--cwd", "/custom/path"])

    call_args = mock_run.call_args
    bd_argv = call_args[0][0]  # positional first arg is the argv list
    assert "--cwd" not in bd_argv
    assert "/custom/path" not in bd_argv


@patch("fleet.cli.BeadsQueue")
@patch("fleet.cli.subprocess.run")
def test_cwd_flag_equals_form(mock_run: MagicMock, mock_queue_cls: MagicMock) -> None:
    """--cwd=/some/path (equals form) is also accepted."""
    mock_run.return_value = _make_completed_process()
    mock_queue = MagicMock()
    mock_queue_cls.return_value = mock_queue

    runner = CliRunner()
    result = runner.invoke(app, ["bd", "create", "Test Task", "--cwd=/equals/path"])

    assert result.exit_code == 0, result.output
    mock_queue.set_cwd.assert_called_once_with("task-abc", "/equals/path")
