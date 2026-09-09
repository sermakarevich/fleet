"""Scripted process doubles for worker tests (no subprocesses, no patching).

Called by ``tests/workers/test_llm_session*.py`` and
``tests/workers/test_compact.py``. :class:`FakeProcess` quacks like
``CoderProcess`` (stdout reader, wait, terminate_group, signal_group) while
:class:`FakeProcessRunner` quacks like ``ProcessRunner``: it records every
start call and hands out the next scripted process. A hanging process
(``hang=True``) feeds no EOF until it is terminated, so monitor kills and
cancels can be scripted without sleeps or real CLIs.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import IO


class FakeProcess:
    """One scripted coder child: canned stdout lines plus an exit code."""

    def __init__(
        self,
        lines: list[str] | None = None,
        exit_code: int | None = 0,
        *,
        hang: bool = False,
        stderr_text: str = "",
    ) -> None:
        self.pid = 4242
        self.pgid = 4242
        self.returncode: int | None = None
        self.terminated = False
        self.signals: list[int] = []
        self.started = asyncio.Event()
        self._lines = list(lines or [])
        self._exit_code = exit_code
        self._hang = hang
        self._stderr_text = stderr_text
        self._done = asyncio.Event()
        self._stdout: asyncio.StreamReader | None = None

    async def _open(self) -> None:
        """Feed the canned lines (StreamReader needs a running loop)."""
        if self._stdout is not None:
            return
        reader = asyncio.StreamReader()
        for line in self._lines:
            reader.feed_data((line + "\n").encode("utf-8"))
        if not self._hang:
            reader.feed_eof()
        self._stdout = reader
        self.started.set()

    @property
    def stdout(self) -> asyncio.StreamReader:
        """The canned stdout the EventStream reads."""
        assert self._stdout is not None, "FakeProcess not opened: start it via FakeProcessRunner"
        return self._stdout

    def signal_group(self, sig: int) -> None:
        """Record the signal; never raises."""
        self.signals.append(sig)

    async def wait(self) -> int | None:
        """Reap the scripted exit code (unblocks when a hang is terminated)."""
        if self.returncode is not None:
            return self.returncode
        if self._hang:
            await self._done.wait()
            return self.returncode
        self.returncode = self._exit_code
        return self.returncode

    async def terminate_group(self, grace_sec: float) -> None:
        """End a hanging process; a finished one is a no-op."""
        _ = grace_sec
        self.terminated = True
        if self.returncode is None:
            self.returncode = self._exit_code
            if self._hang:
                assert self._stdout is not None
                self._stdout.feed_eof()
                self._done.set()


class FakeProcessRunner:
    """Scripted ProcessRunner: records starts, plays queued processes in order."""

    def __init__(self, procs: list[FakeProcess] | None = None) -> None:
        self._procs = list(procs or [])
        self.starts: list[dict] = []

    def add(self, proc: FakeProcess) -> None:
        """Queue one more scripted process for the next start."""
        self._procs.append(proc)

    async def start(
        self,
        argv: list[str],
        env: dict[str, str],
        cwd: Path | str | None,
        *,
        stderr: int | IO[bytes] | None = None,
    ) -> FakeProcess:
        """Record the call, dump scripted stderr, hand out the next process."""
        self.starts.append({"argv": list(argv), "env": dict(env), "cwd": cwd})
        write = getattr(stderr, "write", None)
        proc = self._procs.pop(0) if self._procs else FakeProcess()
        await proc._open()
        if proc._stderr_text and callable(write):
            write(proc._stderr_text.encode("utf-8", errors="replace"))
            flush = getattr(stderr, "flush", None)
            if callable(flush):
                flush()
        return proc

    @property
    def last_env(self) -> dict[str, str]:
        """Env of the most recent start ({} before the first start)."""
        return self.starts[-1]["env"] if self.starts else {}
