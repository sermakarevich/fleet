"""Context-pressure histogram: peak context use as a share of the limit.

Called by ``serve/analytics/summary.py`` (``SECTION`` joins
``SUMMARY_SECTIONS``). Limits resolve per coder/model with the fleet-home
overrides carried by the window; unknown coders fall back to 200k.
"""

from __future__ import annotations

from fleet.coders import context_limit_for
from fleet.serve.analytics.metrics import Section
from fleet.serve.analytics.records import AttemptRecord
from fleet.serve.analytics.window import Window, completed

_FALLBACK_LIMIT = 200_000

_BUCKETS = ("0-25", "25-50", "50-75", "75-100", "100+")

_THRESHOLDS = (("100+", 100), ("75-100", 75), ("50-75", 50), ("25-50", 25))


def _limit_for(record: AttemptRecord, overrides: dict[str, int]) -> int:
    """Context window for the record's coder/model, or the fallback."""
    try:
        limit = context_limit_for(record.coder or "", record.model, overrides)
    except (ValueError, TypeError, IndexError):
        return _FALLBACK_LIMIT
    return limit if limit > 0 else _FALLBACK_LIMIT


def _bucket_for(ratio_pct: float) -> str:
    """Histogram bucket for a usage percentage (a threshold table)."""
    for bucket, threshold in _THRESHOLDS:
        if ratio_pct >= threshold:
            return bucket
    return "0-25"


def compute(records: list[AttemptRecord], window: Window) -> dict:
    """Bucket counts over all completions (never window-filtered)."""
    counts = dict.fromkeys(_BUCKETS, 0)
    for record in completed(records):
        if record.peak_context_tokens is None:
            continue
        ratio = max(record.peak_context_tokens / _limit_for(record, window.context_overrides), 0)
        counts[_bucket_for(ratio * 100)] += 1
    return {"buckets": counts}


SECTION = Section("context_histogram", "Context usage histogram", compute)
