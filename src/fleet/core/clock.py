"""One clock for the whole supervisor: real time in prod, fake time in tests.

Called by ``orchestrator/`` services (claim, reap, leases, stall, triage,
spawn) and ``core/retry_policy.py`` instead of ``datetime.now`` /
``time.monotonic`` scattered at call sites. Tests build ``FakeClock`` and
hand it to ``SupervisorState`` instead of monkeypatching ``datetime``.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from typing import Protocol


class Clock(Protocol):
    """Now in two shapes: wall time for stamps, monotonic for intervals."""

    def now(self) -> datetime:
        """Current UTC wall time (timezone-aware)."""
        ...

    def monotonic(self) -> float:
        """Monotonic seconds for interval math (never goes backwards)."""
        ...


class SystemClock:
    """The production clock: real wall time and real monotonic time."""

    def now(self) -> datetime:
        """Current UTC wall time."""
        return datetime.now(tz=UTC)

    def monotonic(self) -> float:
        """Monotonic seconds from the OS."""
        return time.monotonic()


class FakeClock:
    """A hand-advanced clock for tests; starts at *start*, steps by *step*."""

    def __init__(self, start: datetime | None = None, step_s: float = 0.0) -> None:
        self._now = start or datetime.now(tz=UTC)
        self._tick = 0.0
        self._step = step_s

    def now(self) -> datetime:
        """The fake wall time (advances by *step_s* per call when set)."""
        current = self._now
        if self._step:
            self._now = current + timedelta(seconds=self._step)
        return current

    def monotonic(self) -> float:
        """The fake monotonic time (advances by *step_s* per call when set)."""
        current = self._tick
        if self._step:
            self._tick = current + self._step
        return current

    def advance(self, seconds: float) -> None:
        """Move both wall and monotonic time forward by *seconds*."""
        self._now = self._now + timedelta(seconds=seconds)
        self._tick += seconds

    def set(self, moment: datetime) -> None:
        """Jump wall time to *moment* (monotonic is untouched)."""
        self._now = moment
