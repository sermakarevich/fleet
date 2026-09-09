"""Tests for shared CLI options: defaults, serve_stored, endpoint resolution."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from fleet.cli import options
from fleet.cli.main import app
from fleet.core.config import RuntimeConfig
from fleet.observability.pidfile import PidFile

runner = CliRunner()


def test_serve_defaults_come_from_runtime_config() -> None:
    defaults = RuntimeConfig()
    assert options.DEFAULT_SERVE_HOST == defaults.serve_host == "0.0.0.0"
    assert options.DEFAULT_SERVE_PORT == defaults.serve_port == 7890


def test_serve_stored_none_when_no_pidfile(tmp_path: Path) -> None:
    with patch("fleet.cli.options.read_pid_record", return_value=None):
        assert options.serve_stored(tmp_path) is None


def test_serve_stored_reads_host_and_port(tmp_path: Path) -> None:
    record = PidFile(pid=999, started_at="x", extra={"host": "127.0.0.1", "port": 8080})
    with patch("fleet.cli.options.read_pid_record", return_value=record):
        assert options.serve_stored(tmp_path) == ("127.0.0.1", 8080)


def test_serve_stored_none_when_incomplete(tmp_path: Path) -> None:
    record = PidFile(pid=999, started_at="x", extra={"port": 8080})
    with patch("fleet.cli.options.read_pid_record", return_value=record):
        assert options.serve_stored(tmp_path) is None


def test_serve_stored_none_when_garbage(tmp_path: Path) -> None:
    record = PidFile(pid=999, started_at="x", extra={"host": "", "port": "nope"})
    with patch("fleet.cli.options.read_pid_record", return_value=record):
        assert options.serve_stored(tmp_path) is None


def test_resolve_explicit_flags_win(tmp_path: Path) -> None:
    with patch("fleet.cli.options.read_pid_record") as mock_read:
        assert options.resolve_serve_endpoint(tmp_path, 1234, "127.0.0.1") == (
            "127.0.0.1",
            1234,
        )
        mock_read.assert_called_once()


def test_resolve_falls_back_to_stored(tmp_path: Path) -> None:
    record = PidFile(pid=999, started_at="x", extra={"host": "127.0.0.1", "port": 8080})
    with patch("fleet.cli.options.read_pid_record", return_value=record):
        assert options.resolve_serve_endpoint(tmp_path, None, None) == ("127.0.0.1", 8080)


def test_resolve_falls_back_to_defaults(tmp_path: Path) -> None:
    with patch("fleet.cli.options.read_pid_record", return_value=None):
        assert options.resolve_serve_endpoint(tmp_path, None, None) == (
            options.DEFAULT_SERVE_HOST,
            options.DEFAULT_SERVE_PORT,
        )


def test_serve_start_help_lists_shared_options() -> None:
    result = runner.invoke(app, ["serve", "start", "--help"])
    assert result.exit_code == 0
    assert "--host" in result.output
    assert "--port" in result.output
