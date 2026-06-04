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

from fleet.daemon import Daemon, DaemonSpec, StartResult, _pid_alive


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
# _pid_alive
# ---------------------------------------------------------------------------


def test_pid_alive_true_for_self() -> None:
    assert _pid_alive(os.getpid()) is True


def test_pid_alive_false_for_reaped_child() -> None:
    proc = subprocess.Popen([sys.executable, "-c", ""])
    proc.wait()  # reap so the PID is fully gone
    assert _pid_alive(proc.pid) is False


def test_pid_alive_false_for_nonpositive() -> None:
    assert _pid_alive(0) is False
    assert _pid_alive(-1) is False


# ---------------------------------------------------------------------------
# PID-file read / write
# ---------------------------------------------------------------------------


def test_write_and_read_pidfile_roundtrip(tmp_path: Path) -> None:
    d = Daemon(make_spec(tmp_path, extra={"port": 7890}))
    d._write_pidfile(4242)
    data = d.read_pidfile()
    assert data is not None
    assert data["pid"] == 4242
    assert data["port"] == 7890
    assert "started_at" in data
    assert d.pid() == 4242


def test_read_bare_int_pidfile(tmp_path: Path) -> None:
    """Backward compatible with the supervisor route's bare-int PID file."""
    spec = make_spec(tmp_path)
    spec.pidfile.parent.mkdir(parents=True, exist_ok=True)
    spec.pidfile.write_text("12345", encoding="utf-8")
    assert Daemon(spec).pid() == 12345


def test_read_missing_pidfile(tmp_path: Path) -> None:
    assert Daemon(make_spec(tmp_path)).read_pidfile() is None
    assert Daemon(make_spec(tmp_path)).pid() is None


# ---------------------------------------------------------------------------
# start
# ---------------------------------------------------------------------------


def test_start_spawns_detached_and_records_pid(tmp_path: Path, monkeypatch) -> None:
    spec = make_spec(tmp_path, extra={"port": 1234})
    d = Daemon(spec)
    popen = MagicMock(return_value=MagicMock(pid=4242))
    monkeypatch.setattr("fleet.daemon.subprocess.Popen", popen)
    monkeypatch.setattr("fleet.daemon.time.sleep", lambda *_: None)
    monkeypatch.setattr("fleet.daemon._pid_alive", lambda pid: True)

    result = d.start()

    assert result == StartResult(pid=4242, already_running=False, alive=True)
    assert d.read_pidfile()["pid"] == 4242
    assert d.read_pidfile()["port"] == 1234
    assert popen.called
    _, kwargs = popen.call_args
    assert kwargs.get("start_new_session") is True
    assert kwargs.get("stdin") is subprocess.DEVNULL


def test_start_idempotent_when_already_running(tmp_path: Path, monkeypatch) -> None:
    d = Daemon(make_spec(tmp_path))
    d._write_pidfile(os.getpid())  # a genuinely-alive PID
    popen = MagicMock()
    monkeypatch.setattr("fleet.daemon.subprocess.Popen", popen)

    result = d.start()

    assert result.already_running is True
    assert result.pid == os.getpid()
    assert not popen.called  # did not spawn a second daemon


def test_start_detects_immediate_exit(tmp_path: Path, monkeypatch) -> None:
    """A daemon that dies during the startup probe is reported not-alive."""
    d = Daemon(make_spec(tmp_path))
    monkeypatch.setattr(
        "fleet.daemon.subprocess.Popen", MagicMock(return_value=MagicMock(pid=4242))
    )
    monkeypatch.setattr("fleet.daemon.time.sleep", lambda *_: None)
    monkeypatch.setattr("fleet.daemon._pid_alive", lambda pid: False)

    result = d.start()

    assert result.alive is False
    assert d.read_pidfile() is None  # stale PID file cleared


def test_start_real_process_is_alive(tmp_path: Path, monkeypatch) -> None:
    """End-to-end: real detached spawn, PID file written, process actually live."""
    monkeypatch.setattr("fleet.daemon.STARTUP_PROBE_SEC", 0.2)
    d = Daemon(make_spec(tmp_path, argv=[sys.executable, "-c", "import time; time.sleep(30)"]))
    result = d.start()
    try:
        assert result.alive is True
        assert d.is_alive() is True
        assert d.read_pidfile()["pid"] == result.pid
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
    d = Daemon(make_spec(tmp_path, stop_timeout=5.0))
    d._write_pidfile(4242)
    kill = MagicMock()
    killpg = MagicMock()
    monkeypatch.setattr("fleet.daemon.os.kill", kill)
    monkeypatch.setattr("fleet.daemon.os.killpg", killpg)
    # alive at the pre-SIGTERM guard, dead on the first poll afterwards
    monkeypatch.setattr("fleet.daemon._pid_alive", MagicMock(side_effect=[True, False]))
    monkeypatch.setattr("fleet.daemon.time.sleep", lambda *_: None)

    assert d.stop() is True
    assert kill.call_args[0] == (4242, signal.SIGTERM)
    assert not killpg.called  # graceful — no escalation
    assert d.read_pidfile() is None


def test_stop_escalates_to_sigkill_on_timeout(tmp_path: Path, monkeypatch) -> None:
    d = Daemon(make_spec(tmp_path, stop_timeout=0.0))  # deadline already passed
    d._write_pidfile(4242)
    monkeypatch.setattr("fleet.daemon.os.kill", MagicMock())
    monkeypatch.setattr("fleet.daemon.os.getpgid", lambda pid: pid)
    killpg = MagicMock()
    monkeypatch.setattr("fleet.daemon.os.killpg", killpg)
    monkeypatch.setattr("fleet.daemon._pid_alive", lambda pid: True)  # never dies
    monkeypatch.setattr("fleet.daemon.time.sleep", lambda *_: None)

    assert d.stop() is True
    killpg.assert_called_once_with(4242, signal.SIGKILL)
    assert d.read_pidfile() is None


def test_stop_when_not_running_is_noop(tmp_path: Path) -> None:
    assert Daemon(make_spec(tmp_path)).stop() is False


def test_stop_clears_stale_pidfile(tmp_path: Path, monkeypatch) -> None:
    spec = make_spec(tmp_path)
    d = Daemon(spec)
    d._write_pidfile(4242)
    monkeypatch.setattr("fleet.daemon._pid_alive", lambda pid: False)
    assert d.stop() is False
    assert not spec.pidfile.exists()


# ---------------------------------------------------------------------------
# restart
# ---------------------------------------------------------------------------


def test_restart_runs_hook_before_stop_before_start(tmp_path: Path, monkeypatch) -> None:
    d = Daemon(make_spec(tmp_path))
    calls: list[str] = []
    monkeypatch.setattr(d, "stop", lambda *a, **k: calls.append("stop") or False)
    monkeypatch.setattr(
        d, "start", lambda: calls.append("start") or StartResult(1, False, True)
    )
    d.restart(before_start=lambda: calls.append("build"))
    assert calls == ["build", "stop", "start"]


def test_restart_aborts_when_hook_raises(tmp_path: Path, monkeypatch) -> None:
    """A failing pre-step (e.g. `make ui-build`) must not stop the running daemon."""
    d = Daemon(make_spec(tmp_path))
    calls: list[str] = []
    monkeypatch.setattr(d, "stop", lambda *a, **k: calls.append("stop"))
    monkeypatch.setattr(d, "start", lambda: calls.append("start"))

    def boom() -> None:
        raise RuntimeError("build failed")

    with pytest.raises(RuntimeError):
        d.restart(before_start=boom)
    assert calls == []  # neither stop nor start ran


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


def test_status_running(tmp_path: Path) -> None:
    d = Daemon(make_spec(tmp_path, extra={"port": 7890}))
    d._write_pidfile(os.getpid())
    st = d.status()
    assert st.running is True
    assert st.pid == os.getpid()
    assert st.extra.get("port") == 7890
    assert st.started_at is not None


def test_status_stopped(tmp_path: Path) -> None:
    st = Daemon(make_spec(tmp_path)).status()
    assert st.running is False
    assert st.pid is None


def test_status_cleans_stale_pidfile(tmp_path: Path, monkeypatch) -> None:
    spec = make_spec(tmp_path)
    d = Daemon(spec)
    d._write_pidfile(4242)
    monkeypatch.setattr("fleet.daemon._pid_alive", lambda pid: False)
    st = d.status()
    assert st.running is False
    assert not spec.pidfile.exists()
