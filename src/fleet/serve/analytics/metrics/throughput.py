"""Completion throughput: finished tasks per time bucket by outcome.

Called by ``serve/analytics/summary.py`` (``SECTION`` joins
``SUMMARY_SECTIONS``). Bucket labels come from ``window.bucket_key``.
"""

from __future__ import annotations

from fleet.serve.analytics.metrics import Section
from fleet.serve.analytics.records import AttemptRecord
from fleet.serve.analytics.window import Window, completed, in_window
from fleet.state.events import parse_iso


def compute(records: list[AttemptRecord], window: Window) -> dict:
    """Success/failed/blocked counts per bucket over windowed completions."""
    buckets: dict[str, dict] = {}
    for record in completed([r for r in records if in_window(r, window)]):
        if not record.last_ts:
            continue
        moment = parse_iso(record.last_ts)
        if moment is None:
            continue
        key = window.bucket_key(moment)
        bucket = buckets.setdefault(key, {"bucket": key, "success": 0, "failed": 0, "blocked": 0})
        if record.outcome in bucket:
            bucket[record.outcome] += 1
    ordered = sorted(buckets.values(), key=lambda row: row["bucket"])
    return {"bucket_size": window.bucket_size, "buckets": ordered}


SECTION = Section("throughput", "Completion throughput", compute)
