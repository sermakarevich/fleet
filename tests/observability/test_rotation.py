"""Tests for daemon/supervisor log rotation. Mirrors the source path."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import fleet.observability.daemon as daemon_mod
from fleet.core.iso import now_iso
from fleet.observability.daemon import DaemonSpec, start
from fleet.state.atomic import rotate_overgrown
from fleet.state.journal import setup_supervisor_logger


def test_small_file_is_left_alone(tmp_path: Path) -> None:
    """Under budget: no backup, content untouched."""
    path = tmp_path / "serve.daemon.log"
    path.write_text("tiny\n", encoding="utf-8")
    rotate_overgrown(path, max_bytes=1024, keep=2)
    assert path.read_text(encoding="utf-8") == "tiny\n"
    assert not (tmp_path / "serve.daemon.log.1").exists()


def test_missing_file_is_noop(tmp_path: Path) -> None:
    rotate_overgrown(tmp_path / "nope.log", max_bytes=10, keep=2)  # must not raise


def test_overgrown_file_shifts_chain_and_drops_oldest(tmp_path: Path) -> None:
    """log -> .1, .1 -> .2, .2 (the oldest, keep=2) is dropped."""
    log = tmp_path / "serve.daemon.log"
    log.write_text("new\n", encoding="utf-8")
    (tmp_path / "serve.daemon.log.1").write_text("old1\n", encoding="utf-8")
    (tmp_path / "serve.daemon.log.2").write_text("old2\n", encoding="utf-8")
    rotate_overgrown(log, max_bytes=4, keep=2)
    assert not log.exists()  # caller re-opens it fresh for append
    assert (tmp_path / "serve.daemon.log.1").read_text(encoding="utf-8") == "new\n"
    assert (tmp_path / "serve.daemon.log.2").read_text(encoding="utf-8") == "old1\n"


def test_daemon_start_rotates_overgrown_log(tmp_path: Path, monkeypatch) -> None:
    """start() rotates the stdout/stderr log before appending to it."""
    monkeypatch.setattr("fleet.observability.daemon.LOG_ROTATE_BYTES", 16)
    spec = DaemonSpec(
        name="svc",
        pidfile=tmp_path / ".svc.pid",
        logfile=tmp_path / "logs" / "svc.log",
        argv=[sys.executable, "-c", "import time; time.sleep(30)"],
        cwd=tmp_path,
        stop_timeout=5.0,
    )
    spec.logfile.parent.mkdir(parents=True, exist_ok=True)
    spec.logfile.write_text("x" * 64, encoding="utf-8")
    monkeypatch.setattr(
        "fleet.observability.daemon.subprocess.Popen",
        MagicMock(return_value=MagicMock(pid=4242)),
    )
    monkeypatch.setattr("fleet.observability.daemon.time.sleep", lambda *_: None)
    monkeypatch.setattr(daemon_mod, "pid_alive", lambda pid: True)

    result = start(spec)

    assert result.alive is True
    rotated = spec.logfile.with_name(spec.logfile.name + ".1")
    assert rotated.exists()
    assert rotated.read_text(encoding="utf-8") == "x" * 64


def test_supervisor_logger_rotates_overgrown_jsonl(tmp_path: Path, monkeypatch) -> None:
    """The supervisor structlog file gets the same rotation policy."""
    monkeypatch.setattr("fleet.state.journal.LOG_ROTATE_BYTES", 16)
    fleet_path = tmp_path / f"fleet-{now_iso()[:10]}.jsonl"
    fleet_path.write_text("y" * 64, encoding="utf-8")

    setup_supervisor_logger(tmp_path)

    rotated = tmp_path / (fleet_path.name + ".1")
    assert rotated.exists()
    assert rotated.read_text(encoding="utf-8") == "y" * 64
