"""Tests for workers/session/process.py: CoderProcess lifecycle and kill path."""

from __future__ import annotations

import asyncio
import os
import signal
import sys
from pathlib import Path

from fleet.workers.session.process import CoderProcess

_SLEEPER = [sys.executable, "-c", "import threading; threading.Event().wait()"]
_IGNORER = [
    sys.executable,
    "-c",
    "import signal, threading; "
    "signal.signal(signal.SIGTERM, signal.SIG_IGN); threading.Event().wait()",
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


def test_terminate_group_escalates_once(tmp_path: Path) -> None:
    """A child ignoring SIGTERM gets exactly one TERM then one KILL."""
    signals: list[int] = []

    async def _run() -> None:
        proc = await _start(_IGNORER, tmp_path)
        real_signal = proc.signal_group

        def _recording(sig: int) -> None:
            signals.append(sig)
            real_signal(sig)

        proc.signal_group = _recording  # type: ignore[method-assign]
        # Let the child install its SIGTERM handler before signalling;
        # a fixed pause is inherent here (child-side readiness, no signal).
        await asyncio.sleep(0.5)
        await proc.terminate_group(0.5)
        assert proc.returncode == -signal.SIGKILL

    asyncio.run(_run())
    assert signals == [signal.SIGTERM, signal.SIGKILL]


def test_terminate_group_idempotent(tmp_path: Path) -> None:
    """Calls after the reap send nothing and raise nothing."""
    signals: list[int] = []

    async def _run() -> None:
        proc = await _start(_SLEEPER, tmp_path)
        real_signal = proc.signal_group

        def _recording(sig: int) -> None:
            signals.append(sig)
            real_signal(sig)

        proc.signal_group = _recording  # type: ignore[method-assign]
        await proc.terminate_group(5.0)
        await proc.terminate_group(5.0)
        await proc.terminate_group(5.0)
        assert proc.returncode == -signal.SIGTERM

    asyncio.run(_run())
    assert signals == [signal.SIGTERM]
