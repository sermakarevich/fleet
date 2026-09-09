"""The one owner of the coder subprocess and its process group.

:class:`CoderProcess` wraps ``asyncio.create_subprocess_exec`` with
``start_new_session`` semantics so every coder CLI runs in its own process
group. :meth:`CoderProcess.terminate_group` is the single
SIGTERM-wait-SIGKILL path every caller uses. :class:`ProcessRunner` is the
seam tests script against: production code takes a
:class:`SubprocessRunner` (the default, which spawns for real) while tests
inject a fake that returns scripted processes. Callers are
``workers/llm_session.py`` (``LlmSession``) and ``workers/compact.py``.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
from pathlib import Path
from typing import IO, Protocol

# Stdout buffer per process: the default 64 KB StreamReader limit dies on
# large MCP tool results (full papers, transcripts), so reads use a manual
# readline loop and oversize lines are skipped by EventStream instead.
STREAM_BUFFER_BYTES = 100 * 1024 * 1024

# Grace between SIGTERM and SIGKILL for monitor-triggered kills (context
# pressure, timeout, rate limit, provider errors). Shutdown cancels use
# core.limits.SHUTDOWN_GRACE_SEC instead.
KILL_GRACE_SEC = 5.0


class CoderProcess:
    """A running coder CLI subprocess; owns its process group."""

    def __init__(self, proc: asyncio.subprocess.Process) -> None:
        self._proc = proc

    @classmethod
    async def start(
        cls,
        argv: list[str],
        env: dict[str, str],
        cwd: Path | str | None,
        *,
        stderr: int | IO[bytes] | None = asyncio.subprocess.DEVNULL,
    ) -> CoderProcess:
        """Spawn the coder CLI in its own process group with piped stdout."""
        proc = await asyncio.create_subprocess_exec(
            *argv,
            env=env,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=stderr,
            stdin=asyncio.subprocess.DEVNULL,
            start_new_session=True,
        )
        assert proc.stdout is not None
        proc.stdout._limit = STREAM_BUFFER_BYTES  # type: ignore[attr-defined]  # private asyncio buffer knob; owned here
        return cls(proc)

    @property
    def pid(self) -> int:
        """The child's pid."""
        return self._proc.pid

    @property
    def pgid(self) -> int:
        """The child's process-group id (the pid when lookup fails)."""
        try:
            return os.getpgid(self._proc.pid)
        except OSError:
            return self._proc.pid

    @property
    def returncode(self) -> int | None:
        """The child's exit code, or None while it runs."""
        return self._proc.returncode

    @property
    def stdout(self) -> asyncio.StreamReader:
        """The child's piped stdout, read by EventStream."""
        assert self._proc.stdout is not None
        return self._proc.stdout

    def signal_group(self, sig: int) -> None:
        """Send one signal to the group; fire-and-forget, never raises."""
        _signal_group(self, sig)

    async def wait(self) -> int | None:
        """Wait until the child is reaped; return its exit code."""
        return await self._proc.wait()

    async def terminate_group(self, grace_sec: float) -> None:
        """SIGTERM the group, wait *grace_sec*, escalate to SIGKILL once.

        No-op when the child is already reaped, so concurrent killers
        (a monitor verdict racing a cancel) are safe.
        """
        if self._proc.returncode is not None:
            return
        _signal_group(self, signal.SIGTERM)
        try:
            await asyncio.wait_for(self._proc.wait(), timeout=grace_sec)
        except TimeoutError:
            if self._proc.returncode is not None:
                return
            _signal_group(self, signal.SIGKILL)
            await self._proc.wait()


def _signal_group(proc: CoderProcess, sig: int) -> None:
    """Signal the child's whole process group; fall back to the child alone."""
    try:
        os.killpg(proc.pgid, sig)
    except (ProcessLookupError, PermissionError, OSError):
        with contextlib.suppress(ProcessLookupError, OSError):
            proc._proc.send_signal(sig)


class ProcessRunner(Protocol):
    """The spawn seam: start a coder child without touching asyncio directly."""

    async def start(
        self,
        argv: list[str],
        env: dict[str, str],
        cwd: Path | str | None,
        *,
        stderr: int | IO[bytes] | None = asyncio.subprocess.DEVNULL,
    ) -> CoderProcess:
        """Spawn the coder CLI and return its process handle."""
        ...


class SubprocessRunner:
    """The production runner: spawn a real coder subprocess per start."""

    async def start(
        self,
        argv: list[str],
        env: dict[str, str],
        cwd: Path | str | None,
        *,
        stderr: int | IO[bytes] | None = asyncio.subprocess.DEVNULL,
    ) -> CoderProcess:
        """Spawn the coder CLI in its own process group with piped stdout."""
        return await CoderProcess.start(argv, env, cwd, stderr=stderr)
