"""Live event feed from a coder process's stdout.

:class:`EventStream` turns stdout lines into normalized ``Event``s (via
``coder.normalize_event``), appends each to ``attempts/<n>/events.jsonl``,
and tracks timing for the monitors. Stderr is file-backed (the attempt's
``log.stderr`` via the task log, or discarded), so it surfaces as
:attr:`EventStream.stderr_tail` rather than a live feed. Callers are
``workers/llm_session.py`` (``run_monitored``) and ``workers/compact.py``.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fleet.coders.base import Coder
from fleet.core.task import Event
from fleet.state.journal import append_event

from .process import CoderProcess

_STDERR_TAIL_BYTES = 2048


def _read_file_tail(path: Path, max_bytes: int = _STDERR_TAIL_BYTES) -> str | None:
    """Last *max_bytes* of *path* as text, or None when the file is missing."""
    if not path.exists():
        return None
    with path.open("rb") as f:
        f.seek(0, 2)
        size = f.tell()
        f.seek(max(0, size - max_bytes))
        return f.read().decode("utf-8", errors="replace")


class EventStream:
    """Async iterator of normalized coder events with timing and stderr tail."""

    def __init__(
        self,
        proc: CoderProcess,
        coder: Coder,
        *,
        attempt_dir: Path,
        started_at: datetime,
        stderr_path: Path | None = None,
        log: Any = None,
        task_id: str = "",
    ) -> None:
        self._proc = proc
        self._coder = coder
        self._attempt_dir = attempt_dir
        self._stderr_path = stderr_path
        self._log = log
        self._task_id = task_id
        self.last_stdout_at = started_at
        self.last_event_at = started_at

    def __aiter__(self) -> AsyncIterator[Event]:
        return self._read()

    async def _read(self) -> AsyncIterator[Event]:
        """Yield normalized events until stdout closes; skip oversize lines."""
        stdout = self._proc.stdout
        while True:
            try:
                raw_bytes = await stdout.readline()
            except asyncio.LimitOverrunError as exc:
                if self._log is not None:
                    self._log.warning(
                        "stdout_line_overrun",
                        task_id=self._task_id,
                        consumed=exc.consumed,
                    )
                continue
            if not raw_bytes:
                return
            now = datetime.now(tz=UTC)
            self.last_stdout_at = now
            evt = self._coder.normalize_event(
                raw_bytes.decode("utf-8", errors="replace").rstrip("\n")
            )
            if evt is None:
                continue
            if evt.session_id:
                # Tags the run for probe_health, telling this run's provider
                # errors apart from other sessions sharing the CLI log file.
                self._coder.current_session_id = evt.session_id  # type: ignore[attr-defined]  # per-run session tag; owned by the stream
            append_event(self._attempt_dir, evt)
            self.last_event_at = now
            yield evt

    @property
    def stderr_tail(self) -> str | None:
        """Last bytes of the stderr file, or None with no stderr file."""
        if self._stderr_path is None:
            return None
        return _read_file_tail(self._stderr_path)
