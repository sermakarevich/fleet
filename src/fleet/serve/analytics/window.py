"""The time window every analytics metric computes against.

Called by ``serve/analytics/summary.py`` (``build_window``) and by every
``serve/analytics/metrics/*`` module (``in_window``, ``completed``,
``bucket_key``). ``context_overrides`` rides along so the context histogram
needs no extra arguments.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fleet.serve.analytics.records import AttemptRecord
from fleet.state.events import parse_iso
from fleet.state.task_summary import context_overrides_for_home

#: Windows this short get hour buckets; longer ones get day buckets.
HOURLY_BUCKET_MAX_DAYS = 3

#: Outcomes that count a task as finished.
COMPLETED_OUTCOMES = ("success", "failed", "blocked")


@dataclass
class Window:
    """One summary call's time range plus bucketing and context config."""

    days: int = 0
    cutoff: datetime | None = None
    now: datetime = field(default_factory=lambda: datetime.now(tz=UTC))
    bucket_size: str = "day"
    context_overrides: dict[str, int] = field(default_factory=dict)

    def bucket_key(self, moment: datetime) -> str:
        """Bucket label for *moment*: hour ISO text or day ISO date."""
        if self.bucket_size == "hour":
            return moment.replace(minute=0, second=0, microsecond=0).isoformat()
        return moment.date().isoformat()


def clamp_days(days: int) -> int:
    """Clamp a requested day range to 0 (all time) .. 365."""
    return 0 if days <= 0 else min(days, 365)


def build_window(fleet_home: Path, days: int) -> Window:
    """Build the window for one summary call over *fleet_home*."""
    clamped = clamp_days(days)
    now = datetime.now(tz=UTC)
    cutoff = None if clamped == 0 else now - timedelta(days=clamped)
    bucket_size = "hour" if 1 <= clamped <= HOURLY_BUCKET_MAX_DAYS else "day"
    return Window(
        days=clamped,
        cutoff=cutoff,
        now=now,
        bucket_size=bucket_size,
        context_overrides=context_overrides_for_home(fleet_home),
    )


def in_window(record: AttemptRecord, window: Window) -> bool:
    """Whether *record* belongs in the window (active tasks always do)."""
    if record.outcome == "active":
        return True
    if window.cutoff is None or record.last_ts is None:
        return True
    last = parse_iso(record.last_ts)
    if last is None:
        return True
    return last >= window.cutoff


def completed(records: list[AttemptRecord]) -> list[AttemptRecord]:
    """Records whose outcome is success, failed or blocked."""
    return [record for record in records if record.outcome in COMPLETED_OUTCOMES]
