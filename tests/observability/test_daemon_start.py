"""Tests for daemon start(): lock, liveness window, spawn failures.

Mirrors observability/daemon.py's start path. `Popen` is mocked for
determinism; no real processes are spawned here (see test_daemon.py for the
one real-process test).
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

import fleet.observability.daemon as daemon_mod
from fleet.observability import pidfile as pidfile_mod
from fleet.observability.daemon import DaemonSpec, start


def make_spec(tmp_path: Path, *, name: str = "svc") -> DaemonSpec:
    return DaemonSpec(
        name=name,
        pidfile=tmp_path / f".{name}.pid",
        logfile=tmp_path / "logs" / f"{name}.log",
        argv=[sys.executable, "-c", "import threading; threading.Event().wait()"],
        cwd=tmp_path,
        stop_timeout=5.0,
        extra={},
    )


def mock_spawn(monkeypatch, *, pid: int = 4242, alive: bool = True) -> MagicMock:
    """Fake Popen + instant sleeps + fixed liveness answer."""
    popen = MagicMock(return_value=MagicMock(pid=pid))
    monkeypatch.setattr("fleet.observability.daemon.subprocess.Popen", popen)
    monkeypatch.setattr("fleet.observability.daemon.time.sleep", lambda *_: None)
    monkeypatch.setattr("fleet.observability.daemon.pid_alive", lambda p: alive)
    return popen


def test_double_start_second_reports_already_running(tmp_path: Path, monkeypatch) -> None:
    """A second start spawns nothing and reports already running."""
    spec = make_spec(tmp_path)
    popen = mock_spawn(monkeypatch, alive=True)

    first = start(spec)
    assert first.alive is True
    assert popen.call_count == 1

    second = start(spec)
    assert second.alive is False
    assert second.detail == "already running"
    assert second.pid == first.pid
    assert popen.call_count == 1  # no second child


def test_concurrent_start_holding_lock_reports_already_running(tmp_path: Path, monkeypatch) -> None:
    """A fresh lock (a start still in flight) blocks a second spawn."""
    spec = make_spec(tmp_path)
    popen = mock_spawn(monkeypatch, alive=True)
    lock = daemon_mod._lock_path(spec)
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.touch()  # another start() created it moments ago, no pidfile yet

    result = start(spec)

    assert result.alive is False
    assert result.detail == "already running"
    assert not popen.called


def test_stale_lock_is_cleared_and_start_proceeds(tmp_path: Path, monkeypatch) -> None:
    """A lock from a crashed start never blocks future starts forever."""
    spec = make_spec(tmp_path)
    popen = mock_spawn(monkeypatch, alive=True)
    lock = daemon_mod._lock_path(spec)
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.touch()
    old = time.time() - (daemon_mod._LOCK_STALE_SEC + 60)
    os.utime(lock, (old, old))

    result = start(spec)

    assert result.alive is True
    assert popen.call_count == 1
    assert not lock.exists()  # released after the start finished


def test_child_dying_inside_window_reports_dead(tmp_path: Path, monkeypatch) -> None:
    """A daemon alive at first probe but gone before the window ends is dead."""
    spec = make_spec(tmp_path)
    popen = MagicMock(return_value=MagicMock(pid=4242))
    monkeypatch.setattr("fleet.observability.daemon.subprocess.Popen", popen)
    monkeypatch.setattr("fleet.observability.daemon.time.sleep", lambda *_: None)
    # Alive for the first probes, then gone — the old single-probe check missed this.
    monkeypatch.setattr(
        "fleet.observability.daemon.pid_alive",
        MagicMock(side_effect=[True, True, False, False]),
    )

    result = start(spec)

    assert result.alive is False
    assert result.detail == "process exited during startup"
    assert pidfile_mod.read(spec.pidfile) is None


def test_popen_failure_returns_typed_result(tmp_path: Path, monkeypatch) -> None:
    """An unspawnable child (missing binary) is a result, never a raw exception."""
    spec = make_spec(tmp_path)
    monkeypatch.setattr(
        "fleet.observability.daemon.subprocess.Popen",
        MagicMock(side_effect=OSError("ssh binary not found")),
    )
    monkeypatch.setattr("fleet.observability.daemon.time.sleep", lambda *_: None)

    result = start(spec)

    assert result.alive is False
    assert result.already_running is False
    assert "ssh binary not found" in result.detail
    assert pidfile_mod.read(spec.pidfile) is None


# ---------------------------------------------------------------------------
# supervisor single-instance: lifetime lock + orphan scan
# ---------------------------------------------------------------------------


def make_supervisor_spec(tmp_path: Path) -> DaemonSpec:
    """A supervisor DaemonSpec rooted at tmp_path (pidfile beside the lock)."""
    spec = make_spec(tmp_path)
    return DaemonSpec(
        name="supervisor",
        pidfile=tmp_path / ".supervisor.pid",
        logfile=spec.logfile,
        argv=spec.argv,
        cwd=tmp_path,
        stop_timeout=5.0,
        extra={},
    )


def test_supervisor_lock_roundtrip(tmp_path: Path) -> None:
    """Holding the lock reports held; releasing reports free."""
    fh = daemon_mod.acquire_supervisor_lock(tmp_path)
    assert fh is not None
    try:
        assert daemon_mod.supervisor_lock_held(tmp_path) is True
    finally:
        daemon_mod.release_supervisor_lock(fh)
    assert daemon_mod.supervisor_lock_held(tmp_path) is False


def test_second_supervisor_start_refused_while_lock_held(tmp_path: Path, monkeypatch) -> None:
    """A supervisor start spawns nothing while another foreground holds the lock."""
    spec = make_supervisor_spec(tmp_path)
    monkeypatch.setattr(daemon_mod, "find_supervisor_orphans", lambda *a, **k: [])
    fh = daemon_mod.acquire_supervisor_lock(tmp_path)
    assert fh is not None
    try:
        popen = mock_spawn(monkeypatch, alive=True)
        result = start(spec)
    finally:
        daemon_mod.release_supervisor_lock(fh)

    assert result.already_running is True
    assert "already running" in result.detail
    assert not popen.called  # did not spawn a duplicate supervisor


def test_supervisor_start_proceeds_after_lock_released(tmp_path: Path, monkeypatch) -> None:
    """Once the previous foreground exits, a supervisor start spawns again."""
    spec = make_supervisor_spec(tmp_path)
    monkeypatch.setattr(daemon_mod, "find_supervisor_orphans", lambda *a, **k: [])
    fh = daemon_mod.acquire_supervisor_lock(tmp_path)
    assert fh is not None
    daemon_mod.release_supervisor_lock(fh)
    popen = mock_spawn(monkeypatch, alive=True)

    result = start(spec)

    assert result.alive is True
    assert popen.call_count == 1


def test_supervisor_start_refused_for_orphan_without_pidfile(tmp_path: Path, monkeypatch) -> None:
    """A live foreground with no pidfile still refuses a second start."""
    spec = make_supervisor_spec(tmp_path)
    assert not spec.pidfile.exists()  # stale/missing pidfile, like the incident
    monkeypatch.setattr(daemon_mod, "find_supervisor_orphans", lambda *a, **k: [78937])
    popen = mock_spawn(monkeypatch, alive=True)

    result = start(spec)

    assert result.already_running is True
    assert result.pid == 78937
    assert not popen.called


def test_argv_match_and_ps_parse(tmp_path: Path) -> None:
    """The scan recognises `python -m fleet run foreground` argv rows."""
    assert (
        daemon_mod._argv_is_supervisor(["/usr/bin/python", "-m", "fleet", "run", "foreground"])
        is True
    )
    assert (
        daemon_mod._argv_is_supervisor(["/usr/bin/python", "-m", "fleet", "run", "status"]) is False
    )
    rows = daemon_mod._parse_ps_output("  PID ARGS\n 1234 python -m fleet run foreground\n")
    assert rows == {1234: ["python", "-m", "fleet", "run", "foreground"]}
