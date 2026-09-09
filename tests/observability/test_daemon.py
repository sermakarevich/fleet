"""Tests for the PID-file daemon manager (fleet-nbu).

Process-control logic (SIGTERM → SIGKILL escalation, idempotent start, restart
ordering) is exercised with `subprocess.Popen` / `os.kill` mocked for
determinism. One real-process test covers the actual spawn → detach → PID-file →
liveness path end to end. PID-file shapes live in test_pidfile.py.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import fleet.observability.daemon as daemon_mod
from fleet.observability import pidfile as pidfile_mod
from fleet.observability.daemon import (
    DaemonSpec,
    StartResult,
    restart,
    start,
    status,
    stop,
)
from fleet.observability.pidfile import PidFile


def make_spec(
    tmp_path: Path,
    *,
    name: str = "svc",
    argv: list[str] | None = None,
    stop_timeout: float = 5.0,
    extra: dict | None = None,
) -> DaemonSpec:
    return DaemonSpec(
        name=name,
        pidfile=tmp_path / f".{name}.pid",
        logfile=tmp_path / "logs" / f"{name}.log",
        argv=argv or [sys.executable, "-c", "import threading; threading.Event().wait()"],
        cwd=tmp_path,
        stop_timeout=stop_timeout,
        extra=extra or {},
    )


def seed_pidfile(spec: DaemonSpec, pid: int, extra: dict | None = None) -> None:
    """Write a v1 pidfile record the way a previous start() would have."""
    spec.pidfile.parent.mkdir(parents=True, exist_ok=True)
    pidfile_mod.write(
        spec.pidfile,
        PidFile(
            pid=pid,
            started_at="2026-09-08T00:00:00+00:00",
            fingerprint=daemon_mod.code_fingerprint(),
            extra=extra if extra is not None else dict(spec.extra),
        ),
    )


# ---------------------------------------------------------------------------
# start
# ---------------------------------------------------------------------------


def test_start_spawns_detached_and_records_pid(tmp_path: Path, monkeypatch) -> None:
    spec = make_spec(tmp_path, extra={"port": 1234})
    popen = MagicMock(return_value=MagicMock(pid=4242))
    monkeypatch.setattr("fleet.observability.daemon.subprocess.Popen", popen)
    monkeypatch.setattr("fleet.observability.daemon.time.sleep", lambda *_: None)
    monkeypatch.setattr("fleet.observability.daemon.pid_alive", lambda pid: True)

    result = start(spec)

    assert result == StartResult(pid=4242, already_running=False, alive=True)
    record = pidfile_mod.read(spec.pidfile)
    assert record is not None
    assert record.pid == 4242
    assert record.extra["port"] == 1234
    assert popen.called
    _, kwargs = popen.call_args
    assert kwargs.get("start_new_session") is True
    assert kwargs.get("stdin") is subprocess.DEVNULL


def test_start_idempotent_when_already_running(tmp_path: Path, monkeypatch) -> None:
    spec = make_spec(tmp_path)
    seed_pidfile(spec, os.getpid())  # a genuinely-alive PID
    popen = MagicMock()
    monkeypatch.setattr("fleet.observability.daemon.subprocess.Popen", popen)

    result = start(spec)

    assert result.already_running is True
    assert result.pid == os.getpid()
    assert result.alive is False
    assert result.detail == "already running"
    assert not popen.called  # did not spawn a second daemon


def test_start_detects_immediate_exit(tmp_path: Path, monkeypatch) -> None:
    """A daemon that dies during the startup window is reported not-alive."""
    spec = make_spec(tmp_path)
    monkeypatch.setattr(
        "fleet.observability.daemon.subprocess.Popen", MagicMock(return_value=MagicMock(pid=4242))
    )
    monkeypatch.setattr("fleet.observability.daemon.time.sleep", lambda *_: None)
    monkeypatch.setattr("fleet.observability.daemon.pid_alive", lambda pid: False)

    result = start(spec)

    assert result.alive is False
    assert result.detail == "process exited during startup"
    assert pidfile_mod.read(spec.pidfile) is None  # stale PID file cleared


def test_start_real_process_is_alive(tmp_path: Path, monkeypatch) -> None:
    """End-to-end: real detached spawn, PID file written, process actually live."""
    monkeypatch.setattr("fleet.observability.daemon.STARTUP_WINDOW_SEC", 0.2)
    keepalive = [sys.executable, "-c", "import threading; threading.Event().wait()"]
    spec = make_spec(tmp_path, argv=keepalive)
    result = start(spec)
    try:
        assert result.alive is True
        assert daemon_mod._is_alive(spec) is True
        record = pidfile_mod.read(spec.pidfile)
        assert record is not None
        assert record.pid == result.pid
    finally:
        try:
            os.kill(result.pid, signal.SIGKILL)
            os.waitpid(result.pid, 0)  # reap to avoid a lingering zombie
        except (ProcessLookupError, ChildProcessError):
            pass


# ---------------------------------------------------------------------------
# stop
# ---------------------------------------------------------------------------


def test_stop_graceful_sigterm(tmp_path: Path, monkeypatch) -> None:
    spec = make_spec(tmp_path, stop_timeout=5.0)
    seed_pidfile(spec, 4242)
    kill = MagicMock()
    killpg = MagicMock()
    monkeypatch.setattr("fleet.observability.daemon.os.kill", kill)
    monkeypatch.setattr("fleet.observability.daemon.os.killpg", killpg)
    # alive at the pre-SIGTERM guard, dead on the first poll afterwards
    monkeypatch.setattr(
        "fleet.observability.daemon.pid_alive", MagicMock(side_effect=[True, False])
    )
    monkeypatch.setattr("fleet.observability.daemon.time.sleep", lambda *_: None)

    assert stop(spec) is True
    assert kill.call_args[0] == (4242, signal.SIGTERM)
    assert not killpg.called  # graceful — no escalation
    assert pidfile_mod.read(spec.pidfile) is None


def test_stop_escalates_to_sigkill_on_timeout(tmp_path: Path, monkeypatch) -> None:
    spec = make_spec(tmp_path, stop_timeout=0.0)  # deadline already passed
    seed_pidfile(spec, 4242)
    monkeypatch.setattr("fleet.observability.daemon.os.kill", MagicMock())
    monkeypatch.setattr("fleet.observability.daemon.os.getpgid", lambda pid: pid)
    killpg = MagicMock()
    monkeypatch.setattr("fleet.observability.daemon.os.killpg", killpg)
    monkeypatch.setattr("fleet.observability.daemon.pid_alive", lambda pid: True)  # never dies
    monkeypatch.setattr("fleet.observability.daemon.time.sleep", lambda *_: None)

    assert stop(spec) is True
    killpg.assert_called_once_with(4242, signal.SIGKILL)
    assert pidfile_mod.read(spec.pidfile) is None


def test_stop_when_not_running_is_noop(tmp_path: Path) -> None:
    assert stop(make_spec(tmp_path)) is False


def test_stop_clears_stale_pidfile(tmp_path: Path, monkeypatch) -> None:
    spec = make_spec(tmp_path)
    seed_pidfile(spec, 4242)
    monkeypatch.setattr("fleet.observability.daemon.pid_alive", lambda pid: False)
    assert stop(spec) is False
    assert not spec.pidfile.exists()


# ---------------------------------------------------------------------------
# restart
# ---------------------------------------------------------------------------


def test_restart_runs_hook_before_stop_before_start(tmp_path: Path, monkeypatch) -> None:
    spec = make_spec(tmp_path)
    calls: list[str] = []
    monkeypatch.setattr(daemon_mod, "stop", lambda *a, **k: calls.append("stop") or False)
    monkeypatch.setattr(
        daemon_mod,
        "start",
        lambda *a, **k: calls.append("start") or StartResult(1, False, True),
    )
    restart(spec, before_start=lambda: calls.append("build"))
    assert calls == ["build", "stop", "start"]


def test_restart_aborts_when_hook_raises(tmp_path: Path, monkeypatch) -> None:
    """A failing pre-step (e.g. `make ui-build`) must not stop the running daemon."""
    spec = make_spec(tmp_path)
    calls: list[str] = []
    monkeypatch.setattr(daemon_mod, "stop", lambda *a, **k: calls.append("stop"))
    monkeypatch.setattr(daemon_mod, "start", lambda *a, **k: calls.append("start"))

    def boom() -> None:
        raise RuntimeError("build failed")

    with pytest.raises(RuntimeError):
        restart(spec, before_start=boom)
    assert calls == []  # neither stop nor start ran


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


def test_status_running(tmp_path: Path) -> None:
    spec = make_spec(tmp_path, extra={"port": 7890})
    seed_pidfile(spec, os.getpid())
    st = status(spec)
    assert st.running is True
    assert st.pid == os.getpid()
    assert st.extra.get("port") == 7890
    assert st.started_at is not None


def test_status_stopped(tmp_path: Path) -> None:
    st = status(make_spec(tmp_path))
    assert st.running is False
    assert st.pid is None


def test_status_cleans_stale_pidfile(tmp_path: Path, monkeypatch) -> None:
    spec = make_spec(tmp_path)
    seed_pidfile(spec, 4242)
    monkeypatch.setattr("fleet.observability.daemon.pid_alive", lambda pid: False)
    st = status(spec)
    assert st.running is False
    assert not spec.pidfile.exists()


def test_status_reports_supervisor_orphans(tmp_path: Path, monkeypatch) -> None:
    """`fleet run status` surfaces foreground pids the pidfile misses."""
    spec = make_spec(tmp_path, name="supervisor")
    seed_pidfile(spec, os.getpid())  # genuinely alive, no pid_alive patch needed
    monkeypatch.setattr(
        "fleet.observability.daemon.find_supervisor_orphans",
        lambda *a, **k: [78937],
    )
    st = status(spec)
    assert st.running is True
    assert st.orphans == (78937,)


def test_status_no_orphans_for_other_daemons(tmp_path: Path) -> None:
    """Non-supervisor daemons never report orphans."""
    spec = make_spec(tmp_path, name="serve")
    seed_pidfile(spec, os.getpid())
    assert status(spec).orphans == ()
