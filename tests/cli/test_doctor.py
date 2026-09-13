"""Tests for `fleet doctor`, `fleet run status` bd lines, and foreground aborts."""

from __future__ import annotations

import subprocess
from unittest.mock import AsyncMock, MagicMock, patch

from fleet.cli.main import app
from fleet.observability.process import ServiceStatus
from fleet.orchestrator.checks import StartupAborted
from tests.cli.conftest import runner


def test_doctor_prints_bd_path_and_version(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """`fleet doctor` prints the resolved `bd` path and its version."""
    fake_bd = tmp_path / "bd"
    fake_bd.write_text("#!/bin/sh\necho hi\n")
    fake_bd.chmod(0o755)
    monkeypatch.setenv("FLEET_BD_BIN", str(fake_bd))
    completed = subprocess.CompletedProcess(
        args=[str(fake_bd), "--version"], returncode=0, stdout="bd 0.1.0", stderr=""
    )
    with patch("fleet.cli.doctor.subprocess.run", return_value=completed):
        result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0, result.output
    assert str(fake_bd) in result.output
    assert "bd 0.1.0" in result.output


def test_doctor_exits_backend_when_bd_missing(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """`fleet doctor` fails loudly when no `bd` binary can be resolved."""
    monkeypatch.delenv("FLEET_BD_BIN", raising=False)
    monkeypatch.setenv("PATH", "")
    monkeypatch.setenv("HOME", "/nonexistent-home-for-bd-test")
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 4, result.output


def test_run_status_prints_bd_path(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """`fleet run status` prints the resolved `bd` path."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    fake_bd = tmp_path / "bd"
    fake_bd.write_text("#!/bin/sh\necho hi\n")
    fake_bd.chmod(0o755)
    monkeypatch.setenv("FLEET_BD_BIN", str(fake_bd))
    with patch("fleet.cli.daemons.service_status") as mock_status:
        mock_status.return_value = ServiceStatus(
            pid=555, alive=True, since="2026-06-04T00:00:00+00:00", fingerprint="abc123"
        )
        result = runner.invoke(app, ["run", "status"])
    assert result.exit_code == 0, result.output
    assert str(fake_bd) in result.output


def test_run_foreground_aborts_without_bd(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """`fleet run foreground` exits BACKEND when the bd startup check aborts."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    with (
        patch("fleet.cli.bootstrap.BeadsQueue"),
        patch("fleet.cli.bootstrap.Supervisor") as mock_cls,
    ):
        mock_sup = MagicMock()
        mock_sup.run = AsyncMock(side_effect=StartupAborted("startup check bd failed"))
        mock_cls.return_value = mock_sup
        result = runner.invoke(app, ["run", "foreground"])
    assert result.exit_code == 4, result.output


def test_serve_foreground_aborts_without_bd(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """`fleet serve foreground` refuses to start when `bd` is missing."""
    with patch(
        "fleet.cli.daemons.check_bd_binary",
        return_value="bd executable not found (checked FLEET_BD_BIN env, PATH)",
    ):
        result = runner.invoke(app, ["serve", "foreground"])
    assert result.exit_code == 4, result.output
