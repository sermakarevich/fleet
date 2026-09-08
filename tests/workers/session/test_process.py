"""Tests for workers/session/process.py: CoderProcess lifecycle and kill path."""

from __future__ import annotations

import asyncio
import os
import signal
import sys
from pathlib import Path

import pytest

import fleet.workers.session.process as process_mod
from fleet.workers.session.process import CoderProcess

_SLEEPER = [sys.executable, "-c", "import time; time.sleep(30)"]
_IGNORER = [
    sys.executable,
    "-c",
    "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(30)",
]


async def _start(argv: list[str], tmp_path: Path) -> CoderProcess:
    return await CoderProcess.start(list(argv), dict(os.environ), tmp_path)


def test_start_reports_pid_and_pgid(tmp_path: Path) -> None:
    async def _run() -> None:
        proc = await _start(_SLEEPER, tmp_path)
        try:
            assert proc.pid > 0
            assert proc.pgid == os.getpgid(proc.pid)
            assert proc.returncode is None
        finally:
            await proc.terminate_group(5.0)

    asyncio.run(_run())


def test_terminate_group_terminates(tmp_path: Path) -> None:
    """SIGTERM alone reaps a cooperative child; no SIGKILL is sent."""

    async def _run() -> None:
        proc = await _start(_SLEEPER, tmp_path)
        await proc.terminate_group(5.0)
        assert proc.returncode == -signal.SIGTERM

    asyncio.run(_run())


def test_terminate_group_escalates_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A child ignoring SIGTERM gets exactly one TERM then one KILL."""
    signals: list[int] = []
    real_signal_group = process_mod._signal_group

    def _recording(proc: CoderProcess, sig: int) -> None:
        signals.append(sig)
        real_signal_group(proc, sig)

    monkeypatch.setattr(process_mod, "_signal_group", _recording)

    async def _run() -> None:
        proc = await _start(_IGNORER, tmp_path)
        # Let the child install its SIGTERM handler before signalling.
        await asyncio.sleep(0.5)
        await proc.terminate_group(0.5)
        assert proc.returncode == -signal.SIGKILL

    asyncio.run(_run())
    assert signals == [signal.SIGTERM, signal.SIGKILL]


def test_terminate_group_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Calls after the reap send nothing and raise nothing."""
    signals: list[int] = []
    real_signal_group = process_mod._signal_group

    def _recording(proc: CoderProcess, sig: int) -> None:
        signals.append(sig)
        real_signal_group(proc, sig)

    monkeypatch.setattr(process_mod, "_signal_group", _recording)

    async def _run() -> None:
        proc = await _start(_SLEEPER, tmp_path)
        await proc.terminate_group(5.0)
        await proc.terminate_group(5.0)
        await proc.terminate_group(5.0)
        assert proc.returncode == -signal.SIGTERM

    asyncio.run(_run())
    assert signals == [signal.SIGTERM]
