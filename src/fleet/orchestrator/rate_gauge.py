from __future__ import annotations

from datetime import UTC, datetime

import structlog

from fleet.core.task import Event, EventKind

_RESET_GRACE_SEC = 5
# Safety-net: if the rate_limit_info event carried no resetsAt, fall back to the
# five-hour window maximum so spawning is never blocked indefinitely.
_FALLBACK_DECAY_SEC = 5 * 3600


class RateGauge:
    def __init__(self, *, log: structlog.BoundLogger) -> None:
        self._log = log
        self.current_usage_pct: float = 0.0
        self.resets_at: int | None = None
        self.last_updated: datetime | None = None

    def update(self, event: Event) -> None:
        if event.kind not in (EventKind.RATE_LIMIT_INFO, EventKind.RATE_LIMIT):
            return
        if event.rate_info is None:
            return
        self.last_updated = datetime.now(tz=UTC)
        usage_pct = event.rate_info.get("usage_pct")
        if usage_pct is not None:
            self.current_usage_pct = float(usage_pct)
        resets_at = event.rate_info.get("resets_at")
        if resets_at is not None:
            self.resets_at = int(resets_at)

    def current_pct(self, now: datetime | None = None) -> float:
        if now is None:
            now = datetime.now(tz=UTC)
        if self.resets_at is not None and now.timestamp() >= self.resets_at + _RESET_GRACE_SEC:
            self.current_usage_pct = 0.0
            self.resets_at = None
        elif (
            self.resets_at is None
            and self.last_updated is not None
            and (now - self.last_updated).total_seconds() >= _FALLBACK_DECAY_SEC
        ):
            # No reset time was provided by the API (edge case). After the maximum
            # five-hour window has elapsed since the last update, clear the gauge so
            # spawning is not blocked indefinitely.
            self.current_usage_pct = 0.0
        return self.current_usage_pct

    def snapshot(self) -> dict:
        return {
            "current_usage_pct": self.current_usage_pct,
            "resets_at": self.resets_at,
            "last_updated": self.last_updated,
        }
