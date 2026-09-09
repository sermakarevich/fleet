"""TDD tests for `fleet bd create --cwd <path>` flag (FR-21, FR-22, FR-23)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from fleet.cli.main import app

BD_CREATE_JSON_RESPONSE = json.dumps({"data": [{"id": "task-abc", "title": "Test Task"}]})


def _make_completed_process(
    stdout: str = BD_CREATE_JSON_RESPONSE, returncode: int = 0
) -> MagicMock:
    proc = MagicMock()
    proc.stdout = stdout
    proc.stderr = ""
    proc.returncode = returncode
    return proc


@patch("fleet.cli.beads.BeadsQueue")
@patch("fleet.beads.client.subprocess.run")
def test_cwd_flag_overrides_getcwd(mock_run: MagicMock, mock_queue_cls: MagicMock) -> None:
    """--cwd /custom/path uses the supplied path, not os.getcwd()."""
    mock_run.return_value = _make_completed_process()
    mock_queue = MagicMock()
    mock_queue_cls.return_value = mock_queue

    runner = CliRunner()
    result = runner.invoke(app, ["bd", "create", "Test Task", "--cwd", "/custom/path"])

    assert result.exit_code == 0, result.output
    mock_queue.set_cwd.assert_called_once_with("task-abc", "/custom/path")


@patch("fleet.cli.beads.BeadsQueue")
@patch("fleet.beads.client.subprocess.run")
@patch("fleet.cli.beads.os.getcwd", return_value="/current/dir")
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


@patch("fleet.cli.beads.BeadsQueue")
@patch("fleet.beads.client.subprocess.run")
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


@patch("fleet.cli.beads.BeadsQueue")
@patch("fleet.beads.client.subprocess.run")
def test_cwd_flag_equals_form(mock_run: MagicMock, mock_queue_cls: MagicMock) -> None:
    """--cwd=/some/path (equals form) is also accepted."""
    mock_run.return_value = _make_completed_process()
    mock_queue = MagicMock()
    mock_queue_cls.return_value = mock_queue

    runner = CliRunner()
    result = runner.invoke(app, ["bd", "create", "Test Task", "--cwd=/equals/path"])

    assert result.exit_code == 0, result.output
    mock_queue.set_cwd.assert_called_once_with("task-abc", "/equals/path")


@patch("fleet.cli.beads.BeadsQueue")
@patch("fleet.beads.client.subprocess.run")
def test_unknown_coder_exits_nonzero(mock_run: MagicMock, mock_queue_cls: MagicMock) -> None:
    """--coder with an unknown name is rejected before bd runs (moved from beads)."""
    mock_queue_cls.return_value = MagicMock()

    runner = CliRunner()
    result = runner.invoke(app, ["bd", "create", "Test Task", "--coder", "no-such-coder"])

    assert result.exit_code != 0
    assert "no-such-coder" in result.output
    mock_run.assert_not_called()


@patch("fleet.beads.client.subprocess.run")
def test_leading_flag_value_not_mistaken_for_subcommand(mock_run: MagicMock) -> None:
    """`fleet bd --db /x list` forwards verbatim (the /x value is not the subcommand)."""
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    runner = CliRunner()
    result = runner.invoke(app, ["bd", "--db", "/tmp/x.db", "list", "--json"])

    assert result.exit_code == 0, result.output
    forwarded = mock_run.call_args[0][0]
    assert forwarded == ["bd", "--db", "/tmp/x.db", "list", "--json"]


@patch("fleet.cli.beads.BeadsQueue")
@patch("fleet.beads.client.subprocess.run")
def test_create_after_leading_global_flag_still_intercepted(
    mock_run: MagicMock, mock_queue_cls: MagicMock
) -> None:
    """`fleet bd --db /x create T` is still treated as create (human summary path)."""
    mock_run.return_value = _make_completed_process(
        json.dumps({"data": [{"id": "fleet-g1", "title": "Titled"}]})
    )
    mock_queue_cls.return_value = MagicMock()

    runner = CliRunner()
    result = runner.invoke(app, ["bd", "--db", "/tmp/x.db", "create", "Titled"])

    assert result.exit_code == 0, result.output
    assert "Created fleet-g1" in result.output


@patch("fleet.cli.beads.BeadsQueue")
@patch("fleet.beads.client.subprocess.run")
def test_json_equals_form_not_duplicated(mock_run: MagicMock, mock_queue_cls: MagicMock) -> None:
    """`--json=true` counts as user-passed JSON; fleet must not append another --json."""
    mock_run.return_value = _make_completed_process()
    mock_queue_cls.return_value = MagicMock()

    runner = CliRunner()
    result = runner.invoke(app, ["bd", "create", "--json=true", "T"])

    assert result.exit_code == 0, result.output
    forwarded = mock_run.call_args[0][0]
    assert "--json=true" in forwarded
    assert "--json" not in forwarded
