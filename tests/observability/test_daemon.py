"""Tests for the PID-file daemon manager (fleet-nbu).

Process-control logic (SIGTERM → SIGKILL escalation, idempotent start, restart
ordering) is exercised with `subprocess.Popen` / `os.kill` mocked for
determinism. One real-process test covers the actual spawn → detach → PID-file →
liveness path end to end.
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
from fleet.observability.daemon import (
    DaemonSpec,
    StartResult,
    read_pidfile,
    restart,
    start,
    status,
    stop,
)


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
        argv=argv or [sys.executable, "-c", "import time; time.sleep(30)"],
        cwd=tmp_path,
        stop_timeout=stop_timeout,
        extra=extra or {},
    )


# ---------------------------------------------------------------------------
# PID-file read / write
# ---------------------------------------------------------------------------


def test_write_and_read_pidfile_roundtrip(tmp_path: Path) -> None:
    spec = make_spec(tmp_path, extra={"port": 7890})
    daemon_mod._write_pidfile(spec, 4242)
    data = read_pidfile(spec)
    assert data is not None
    assert data["pid"] == 4242
    assert data["port"] == 7890
    assert "started_at" in data
    assert daemon_mod._pid(spec) == 4242


def test_read_bare_int_pidfile(tmp_path: Path) -> None:
    """Backward compatible with the supervisor route's bare-int PID file."""
    spec = make_spec(tmp_path)
    spec.pidfile.parent.mkdir(parents=True, exist_ok=True)
    spec.pidfile.write_text("12345", encoding="utf-8")
    assert daemon_mod._pid(spec) == 12345


def test_read_missing_pidfile(tmp_path: Path) -> None:
    assert read_pidfile(make_spec(tmp_path)) is None
    assert daemon_mod._pid(make_spec(tmp_path)) is None


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
    assert read_pidfile(spec)["pid"] == 4242
    assert read_pidfile(spec)["port"] == 1234
    assert popen.called
    _, kwargs = popen.call_args
    assert kwargs.get("start_new_session") is True
    assert kwargs.get("stdin") is subprocess.DEVNULL


def test_start_idempotent_when_already_running(tmp_path: Path, monkeypatch) -> None:
    spec = make_spec(tmp_path)
    daemon_mod._write_pidfile(spec, os.getpid())  # a genuinely-alive PID
    popen = MagicMock()
    monkeypatch.setattr("fleet.observability.daemon.subprocess.Popen", popen)

    result = start(spec)

    assert result.already_running is True
    assert result.pid == os.getpid()
    assert not popen.called  # did not spawn a second daemon


def test_start_detects_immediate_exit(tmp_path: Path, monkeypatch) -> None:
    """A daemon that dies during the startup probe is reported not-alive."""
    spec = make_spec(tmp_path)
    monkeypatch.setattr(
        "fleet.observability.daemon.subprocess.Popen", MagicMock(return_value=MagicMock(pid=4242))
    )
    monkeypatch.setattr("fleet.observability.daemon.time.sleep", lambda *_: None)
    monkeypatch.setattr("fleet.observability.daemon.pid_alive", lambda pid: False)

    result = start(spec)

    assert result.alive is False
    assert read_pidfile(spec) is None  # stale PID file cleared


def test_start_real_process_is_alive(tmp_path: Path, monkeypatch) -> None:
    """End-to-end: real detached spawn, PID file written, process actually live."""
    monkeypatch.setattr("fleet.observability.daemon.STARTUP_PROBE_SEC", 0.2)
    spec = make_spec(tmp_path, argv=[sys.executable, "-c", "import time; time.sleep(30)"])
    result = start(spec)
    try:
        assert result.alive is True
        assert daemon_mod._is_alive(spec) is True
        assert read_pidfile(spec)["pid"] == result.pid
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
    daemon_mod._write_pidfile(spec, 4242)
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
    assert read_pidfile(spec) is None


def test_stop_escalates_to_sigkill_on_timeout(tmp_path: Path, monkeypatch) -> None:
    spec = make_spec(tmp_path, stop_timeout=0.0)  # deadline already passed
    daemon_mod._write_pidfile(spec, 4242)
    monkeypatch.setattr("fleet.observability.daemon.os.kill", MagicMock())
    monkeypatch.setattr("fleet.observability.daemon.os.getpgid", lambda pid: pid)
    killpg = MagicMock()
    monkeypatch.setattr("fleet.observability.daemon.os.killpg", killpg)
    monkeypatch.setattr("fleet.observability.daemon.pid_alive", lambda pid: True)  # never dies
    monkeypatch.setattr("fleet.observability.daemon.time.sleep", lambda *_: None)

    assert stop(spec) is True
    killpg.assert_called_once_with(4242, signal.SIGKILL)
    assert read_pidfile(spec) is None


def test_stop_when_not_running_is_noop(tmp_path: Path) -> None:
    assert stop(make_spec(tmp_path)) is False


def test_stop_clears_stale_pidfile(tmp_path: Path, monkeypatch) -> None:
    spec = make_spec(tmp_path)
    daemon_mod._write_pidfile(spec, 4242)
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
    daemon_mod._write_pidfile(spec, os.getpid())
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
    daemon_mod._write_pidfile(spec, 4242)
    monkeypatch.setattr("fleet.observability.daemon.pid_alive", lambda pid: False)
    st = status(spec)
    assert st.running is False
    assert not spec.pidfile.exists()
