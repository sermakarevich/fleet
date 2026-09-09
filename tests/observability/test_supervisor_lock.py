"""Single-supervisor enforcement: lock, refused starts, orphan reporting.

Regression tests for fleet-xozkr: POST /api/supervisor/restart spawned a
second supervisor that survived later restarts because only the pidfile was
tracked. The foreground now holds an flock lifetime lock, start() refuses
while another foreground is alive, status() reports untracked supervisors,
and stop() terminates them.
"""

from __future__ import annotations

import os
import signal
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import fleet.cli.daemons as climod
import fleet.observability.daemon as daemon_mod
from fleet.cli.main import app
from fleet.observability import pidfile as pidfile_mod
from fleet.observability.daemon import (
    acquire_supervisor_lock,
    release_supervisor_lock,
    start,
    status,
    stop,
    supervisor_lock_held,
    supervisor_spec,
)
from fleet.observability.pidfile import PidFile
from fleet.observability.process import ServiceStatus
from tests.cli.conftest import runner


def mock_spawn(monkeypatch, *, pid: int = 4242) -> MagicMock:
    """Fake Popen + instant sleeps + always-alive liveness."""
    popen = MagicMock(return_value=MagicMock(pid=pid))
    monkeypatch.setattr("fleet.observability.daemon.subprocess.Popen", popen)
    monkeypatch.setattr("fleet.observability.daemon.time.sleep", lambda *_: None)
    monkeypatch.setattr("fleet.observability.daemon.pid_alive", lambda p: True)
    return popen


def no_scan(monkeypatch) -> None:
    """Neutralize the process scan: hermetic, no /proc or ps dependence."""
    monkeypatch.setattr(
        "fleet.observability.daemon.find_supervisor_orphans", lambda home, known: []
    )


def test_second_lock_acquire_refused_while_held(tmp_path: Path) -> None:
    first = acquire_supervisor_lock(tmp_path)
    assert first is not None
    assert supervisor_lock_held(tmp_path) is True
    try:
        assert acquire_supervisor_lock(tmp_path) is None
    finally:
        release_supervisor_lock(first)
    assert supervisor_lock_held(tmp_path) is False
    second = acquire_supervisor_lock(tmp_path)
    assert second is not None
    release_supervisor_lock(second)


def test_start_refused_while_lock_held(tmp_path: Path, monkeypatch) -> None:
    """A live foreground (lock holder) refuses a duplicate start, no spawn."""
    no_scan(monkeypatch)
    popen = mock_spawn(monkeypatch)
    holder = acquire_supervisor_lock(tmp_path)
    assert holder is not None
    try:
        result = start(supervisor_spec(tmp_path))
    finally:
        release_supervisor_lock(holder)

    assert result.already_running is True
    assert result.alive is False
    assert "already running" in result.detail
    assert not popen.called
    assert pidfile_mod.read(tmp_path / ".supervisor.pid") is None


def test_start_refused_by_orphan_scan(tmp_path: Path, monkeypatch) -> None:
    """A pre-lock orphan found by cmdline scan also refuses the start."""
    monkeypatch.setattr(
        "fleet.observability.daemon.find_supervisor_orphans",
        lambda home, known: [4242],
    )
    popen = mock_spawn(monkeypatch)

    result = start(supervisor_spec(tmp_path))

    assert result.already_running is True
    assert result.pid == 4242
    assert not popen.called


def test_status_reports_orphans_when_pidfile_missing(tmp_path: Path, monkeypatch) -> None:
    """`fleet run status` sees supervisors the pidfile misses."""
    monkeypatch.setattr(
        "fleet.observability.daemon.find_supervisor_orphans",
        lambda home, known: [4242],
    )
    st = status(supervisor_spec(tmp_path))
    assert st.running is False
    assert st.orphans == (4242,)


def test_status_lists_orphans_beside_live_record(tmp_path: Path, monkeypatch) -> None:
    spec = supervisor_spec(tmp_path)
    spec.pidfile.parent.mkdir(parents=True, exist_ok=True)
    pidfile_mod.write(
        spec.pidfile,
        PidFile(
            pid=os.getpid(),  # genuinely alive
            started_at="2026-09-08T00:00:00+00:00",
            fingerprint=daemon_mod.code_fingerprint(),
            extra={},
        ),
    )
    monkeypatch.setattr(
        "fleet.observability.daemon.find_supervisor_orphans",
        lambda home, known: [4242],
    )
    st = status(spec)
    assert st.running is True
    assert st.pid == os.getpid()
    assert st.orphans == (4242,)


def test_stop_terminates_untracked_orphans(tmp_path: Path, monkeypatch) -> None:
    """restart heals: stop() kills supervisors the pidfile does not track."""
    monkeypatch.setattr(
        "fleet.observability.daemon.find_supervisor_orphans",
        lambda home, known: [4242],
    )
    kill = MagicMock()
    monkeypatch.setattr("fleet.observability.daemon.os.kill", kill)
    monkeypatch.setattr("fleet.observability.daemon.os.killpg", MagicMock())
    monkeypatch.setattr("fleet.observability.daemon.pid_alive", lambda pid: False)
    monkeypatch.setattr("fleet.observability.daemon.time.sleep", lambda *_: None)

    assert stop(supervisor_spec(tmp_path)) is True
    assert kill.call_args[0] == (4242, signal.SIGTERM)


def test_stop_without_orphans_is_noop(tmp_path: Path, monkeypatch) -> None:
    no_scan(monkeypatch)
    assert stop(supervisor_spec(tmp_path)) is False


def test_run_status_shows_orphan_warning(tmp_path: Path, monkeypatch) -> None:
    """`fleet run status` prints untracked supervisor pids."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    monkeypatch.setattr(
        climod,
        "service_status",
        lambda name, home: ServiceStatus(
            pid=None, alive=False, since=None, fingerprint=None, orphan_pids=(4242,)
        ),
    )
    result = runner.invoke(app, ["run", "status"])
    assert "orphan" in result.output.lower()
    assert "4242" in result.output


def test_foreground_refuses_duplicate_supervisor(tmp_path: Path, monkeypatch) -> None:
    """A second `fleet run foreground` exits with a clear message, no boot."""
    holder = acquire_supervisor_lock(tmp_path)
    assert holder is not None
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    try:
        result = runner.invoke(app, ["run", "foreground"])
    finally:
        release_supervisor_lock(holder)
    assert result.exit_code != 0
    assert "already running" in result.output.lower()


def test_foreground_starts_when_lock_free(tmp_path: Path, monkeypatch) -> None:
    """The lock does not block a sole foreground (bootstrap mocked)."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    with (
        patch("fleet.cli.bootstrap.BeadsQueue"),
        patch("fleet.cli.bootstrap.Supervisor") as mock_cls,
    ):
        mock_sup = MagicMock()
        mock_sup.run = AsyncMock(return_value=0)
        mock_cls.return_value = mock_sup
        result = runner.invoke(app, ["run", "foreground"])
    assert result.exit_code == 0, result.output
    assert not supervisor_lock_held(tmp_path)


def test_real_supervisor_argv_matches_scan(tmp_path: Path) -> None:
    """The daemon's own argv is detected by the orphan scan matcher."""
    spec = supervisor_spec(tmp_path)
    assert daemon_mod._argv_is_supervisor(spec.argv) is True
    assert daemon_mod._argv_is_supervisor([sys.executable, "-m", "fleet", "serve"]) is False
