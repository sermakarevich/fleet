"""Attention flags: tasks needing a look plus raw rate-limit events.

Called by ``serve/analytics/summary.py`` (``SECTION`` and
``RATE_LIMITS_SECTION`` join ``SUMMARY_SECTIONS``). A closed task still
surfaces when it hit a problem flag, labeled by that flag.
"""

from __future__ import annotations

from fleet.serve.analytics.metrics import Section
from fleet.serve.analytics.records import AttemptRecord
from fleet.serve.analytics.window import Window, completed, in_window

_RECENT_LIMIT = 10


def attention_label(record: AttemptRecord) -> str | None:
    """Why *record* needs attention, or None when it looks fine."""
    if record.outcome in ("failed", "blocked"):
        return record.outcome
    if record.noclose:
        return "noclose"
    if record.context_pressure:
        return "context_pressure"
    if record.rate_limited > 0:
        return "rate_limited"
    return None


def compute(records: list[AttemptRecord], window: Window) -> list[dict]:
    """Up to 10 flagged completions, newest first (window ignored)."""
    flagged = [
        (record, label)
        for record in completed(records)
        if (label := attention_label(record)) is not None
    ]
    flagged.sort(key=lambda pair: pair[0].last_ts or "", reverse=True)
    return [
        {
            "id": record.id,
            "title": record.title,
            "coder": record.coder,
            "model": record.model,
            "outcome": label,
            "ended_at": record.last_ts if record.last_ts is not None else "",
        }
        for record, label in flagged[:_RECENT_LIMIT]
    ]


def compute_rate_limits(records: list[AttemptRecord], window: Window) -> list[dict]:
    """Rate-limit events over in-window records, oldest first."""
    events = [
        {"ts": ts, "task_id": record.id}
        for record in records
        if in_window(record, window)
        for ts in record.rate_limit_events
    ]
    events.sort(key=lambda event: event["ts"])
    return events


SECTION = Section("errors_recent", "Tasks needing attention", compute)
RATE_LIMITS_SECTION = Section("rate_limits", "Rate-limit events", compute_rate_limits)
