"""Tests for run/serve daemon commands and UI build (unit under test: cli/daemons.py)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import typer

import fleet.cli.daemons as climod
from fleet.cli.main import app
from fleet.observability.daemon import StartResult
from fleet.observability.pidfile import PidFile
from fleet.observability.process import ServiceStatus
from tests.cli.conftest import runner


def test_run_foreground_invalid_config_coder_exits_nonzero(tmp_path, monkeypatch) -> None:
    """`fleet run foreground` fails fast if the configured default coder is unknown."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    cfg_dir = tmp_path
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "runtime.toml").write_text('coder = "does-not-exist"\n')
    with patch("fleet.cli.bootstrap.BeadsQueue"):
        result = runner.invoke(app, ["run", "foreground"])
    assert result.exit_code == 2
    assert "Available" in result.output or "claude" in result.output


def test_run_foreground_uses_configured_coder(tmp_path, monkeypatch) -> None:
    """`fleet run foreground` constructs Supervisor with no per-run coder override."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    with (
        patch("fleet.cli.bootstrap.BeadsQueue"),
        patch("fleet.cli.bootstrap.Supervisor") as mock_cls,
    ):
        mock_sup = MagicMock()
        mock_sup.run = AsyncMock(return_value=0)
        mock_cls.return_value = mock_sup
        result = runner.invoke(app, ["run", "foreground"])
    assert result.exit_code == 0, result.output + (result.stderr or "")
    _, kwargs = mock_cls.call_args
    assert "coder_override" not in kwargs


def test_bare_run_shows_help_lists_daemon_subcommands() -> None:
    """Bare `fleet run` shows help listing the daemon subcommands."""
    result = runner.invoke(app, ["run"])
    for sub in ("start", "stop", "restart", "status", "foreground"):
        assert sub in result.output, f"Expected '{sub}' in `fleet run` help"


def test_bare_serve_shows_help_lists_daemon_subcommands() -> None:
    result = runner.invoke(app, ["serve"])
    for sub in ("start", "stop", "restart", "status", "foreground"):
        assert sub in result.output, f"Expected '{sub}' in `fleet serve` help"


def test_run_start_reports_started(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    with patch("fleet.cli.daemons.start") as mock_start:
        mock_start.return_value = StartResult(pid=4321, already_running=False, alive=True)
        result = runner.invoke(app, ["run", "start"])
    assert result.exit_code == 0, result.output
    assert "started" in result.output.lower()
    assert "4321" in result.output


def test_run_start_already_running(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    with patch("fleet.cli.daemons.start") as mock_start:
        mock_start.return_value = StartResult(pid=4321, already_running=True, alive=True)
        result = runner.invoke(app, ["run", "start"])
    assert result.exit_code == 0, result.output
    assert "already running" in result.output.lower()


def test_run_start_failure_exits_nonzero(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    with patch("fleet.cli.daemons.start") as mock_start:
        mock_start.return_value = StartResult(pid=4321, already_running=False, alive=False)
        result = runner.invoke(app, ["run", "start"])
    assert result.exit_code != 0
    assert "failed" in result.output.lower()


def test_run_stop_reports_stopped(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    with patch("fleet.cli.daemons.stop") as mock_stop:
        mock_stop.return_value = True
        result = runner.invoke(app, ["run", "stop"])
    assert result.exit_code == 0, result.output
    assert "stopped" in result.output.lower()


def test_run_status_running(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    with patch("fleet.cli.daemons.service_status") as mock_status:
        mock_status.return_value = ServiceStatus(
            pid=555, alive=True, since="2026-06-04T00:00:00+00:00", fingerprint="abc123"
        )
        result = runner.invoke(app, ["run", "status"])
    assert result.exit_code == 0, result.output
    assert "running" in result.output.lower()
    assert "555" in result.output


def test_run_status_stopped_exits_nonzero(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    with patch("fleet.cli.daemons.service_status") as mock_status:
        mock_status.return_value = ServiceStatus(
            pid=None, alive=False, since=None, fingerprint=None
        )
        result = runner.invoke(app, ["run", "status"])
    assert result.exit_code != 0
    assert "stopped" in result.output.lower()


def test_serve_restart_builds_ui_by_default(tmp_path, monkeypatch) -> None:
    """`serve restart` passes the UI-build hook so the SPA is rebuilt first."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    with patch("fleet.cli.daemons.restart") as mock_restart:
        mock_restart.return_value = StartResult(pid=7, already_running=False, alive=True)
        result = runner.invoke(app, ["serve", "restart"])
    assert result.exit_code == 0, result.output
    _, kwargs = mock_restart.call_args
    assert kwargs["before_start"] is climod._build_ui


def test_serve_restart_no_build_skips_hook(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    with patch("fleet.cli.daemons.restart") as mock_restart:
        mock_restart.return_value = StartResult(pid=7, already_running=False, alive=True)
        result = runner.invoke(app, ["serve", "restart", "--no-build"])
    assert result.exit_code == 0, result.output
    _, kwargs = mock_restart.call_args
    assert kwargs["before_start"] is None


def test_serve_restart_reuses_stored_port(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    with (
        patch("fleet.cli.options.read_pid_record") as mock_read,
        patch("fleet.cli.daemons.restart") as mock_restart,
    ):
        mock_read.return_value = PidFile(
            pid=999, started_at="x", extra={"host": "0.0.0.0", "port": 8080}
        )
        mock_restart.return_value = StartResult(pid=7, already_running=False, alive=True)
        result = runner.invoke(app, ["serve", "restart", "--no-build"])
    assert result.exit_code == 0, result.output
    # The spec used for the restart carries the host/port read from the PID file.
    last_spec = mock_restart.call_args[0][0]
    assert last_spec.extra.get("port") == 8080
    assert last_spec.extra.get("host") == "0.0.0.0"


def test_build_ui_runs_just_from_repo_root(tmp_path, monkeypatch) -> None:
    (tmp_path / "justfile").write_text("ui-build:\n\techo hi\n")
    run_mock = MagicMock(return_value=MagicMock(returncode=0))
    monkeypatch.setattr("fleet.cli.subproc.run", run_mock)
    climod._build_ui(tmp_path)
    args, kwargs = run_mock.call_args
    assert args[0] == ["just", "ui-build"]
    assert kwargs["cwd"] == str(tmp_path)


def test_build_ui_skips_when_no_justfile(tmp_path, monkeypatch) -> None:
    run_mock = MagicMock()
    monkeypatch.setattr("fleet.cli.subproc.run", run_mock)
    climod._build_ui(tmp_path)  # no justfile present; must not raise
    assert not run_mock.called


def test_build_ui_raises_on_build_failure(tmp_path, monkeypatch) -> None:
    (tmp_path / "justfile").write_text("ui-build:\n\tfalse\n")
    monkeypatch.setattr("fleet.cli.subproc.run", MagicMock(return_value=MagicMock(returncode=2)))
    with pytest.raises(typer.Exit):
        climod._build_ui(tmp_path)


def test_build_ui_skips_when_just_missing(tmp_path, monkeypatch) -> None:
    (tmp_path / "justfile").write_text("ui-build:\n\techo hi\n")

    def _missing(*args, **kwargs):
        raise FileNotFoundError("just")

    monkeypatch.setattr("fleet.cli.subproc.run", _missing)
    climod._build_ui(tmp_path)  # must not raise
