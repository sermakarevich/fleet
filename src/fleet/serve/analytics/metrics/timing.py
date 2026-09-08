"""Run-time and activity-time metrics: durations, waits, heatmap.

Called by ``serve/analytics/summary.py`` (``SECTION`` joins
``SUMMARY_SECTIONS``) and by ``metrics/outcomes.py`` (``percentile``,
``run_seconds``, ``queue_wait_seconds`` feed the KPI medians).
"""

from __future__ import annotations

from fleet.serve.analytics.metrics import Section
from fleet.serve.analytics.records import AttemptRecord
from fleet.serve.analytics.window import Window, in_window
from fleet.state.events import parse_iso

_DAYS_PER_WEEK = 7
_HOURS_PER_DAY = 24


def percentile(sorted_vals: list[float], pct: float) -> float:
    """Linear-interpolation percentile of an already-sorted list."""
    count = len(sorted_vals)
    if count == 0:
        return 0.0
    if count == 1:
        return sorted_vals[0]
    rank = pct / 100.0 * (count - 1)
    low = int(rank)
    high = low + 1
    frac = rank - low
    if high >= count:
        return sorted_vals[-1]
    return sorted_vals[low] * (1 - frac) + sorted_vals[high] * frac


def median(vals: list[float]) -> float:
    """Median of an unsorted list, or 0 when empty."""
    return percentile(sorted(vals), 50)


def run_seconds(record: AttemptRecord) -> float | None:
    """Seconds between the first and last event, or None when unknown."""
    if not record.first_ts or not record.last_ts:
        return None
    first = parse_iso(record.first_ts)
    last = parse_iso(record.last_ts)
    if first is None or last is None:
        return None
    return (last - first).total_seconds()


def queue_wait_seconds(record: AttemptRecord) -> float | None:
    """Seconds from bead creation to the first event, or None when unknown."""
    if not record.created_at or not record.first_ts:
        return None
    created = parse_iso(record.created_at)
    first = parse_iso(record.first_ts)
    if created is None or first is None:
        return None
    wait = (first - created).total_seconds()
    return wait if wait >= 0 else None


def compute(records: list[AttemptRecord], window: Window) -> list[list[int]]:
    """7x24 weekday-hour event matrix summed over in-window records."""
    heatmap = [[0] * _HOURS_PER_DAY for _ in range(_DAYS_PER_WEEK)]
    for record in records:
        if not in_window(record, window):
            continue
        for key, count in record.hour_hist.items():
            try:
                weekday, hour = (int(part) for part in key.split("-"))
            except ValueError:
                continue
            if 0 <= weekday < _DAYS_PER_WEEK and 0 <= hour < _HOURS_PER_DAY:
                heatmap[weekday][hour] += count
    return heatmap


SECTION = Section("heatmap", "Activity heatmap", compute)
