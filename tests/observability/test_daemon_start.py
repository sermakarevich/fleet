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
