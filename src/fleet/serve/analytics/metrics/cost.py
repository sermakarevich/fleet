"""Token-cost metrics: per-bucket token series plus shared totals.

Called by ``serve/analytics/summary.py`` (``SECTION`` joins
``SUMMARY_SECTIONS``) and by ``metrics/outcomes.py`` (``token_totals``
feeds the KPI token sums, so the two stay in agreement).
"""

from __future__ import annotations

from fleet.serve.analytics.metrics import Section
from fleet.serve.analytics.records import AttemptRecord
from fleet.serve.analytics.window import Window, completed, in_window
from fleet.state.events import parse_iso


def token_totals(records: list[AttemptRecord]) -> dict[str, int]:
    """Summed token counters over *records* (already window-filtered)."""
    return {
        "total_output_tokens": sum(record.output_tokens for record in records),
        "total_input_tokens": sum(record.input_tokens for record in records),
        "total_cache_read_tokens": sum(record.cache_read_tokens for record in records),
        "total_cache_creation_tokens": sum(record.cache_creation_tokens for record in records),
    }


def compute(records: list[AttemptRecord], window: Window) -> dict:
    """Output/input/cache tokens per time bucket over windowed completions."""
    buckets: dict[str, dict] = {}
    for record in completed([r for r in records if in_window(r, window)]):
        if not record.last_ts:
            continue
        moment = parse_iso(record.last_ts)
        if moment is None:
            continue
        key = window.bucket_key(moment)
        bucket = buckets.setdefault(
            key,
            {"bucket": key, "output_tokens": 0, "input_tokens": 0, "cache_tokens": 0},
        )
        bucket["output_tokens"] += record.output_tokens
        bucket["input_tokens"] += record.input_tokens
        bucket["cache_tokens"] += record.cache_read_tokens + record.cache_creation_tokens
    ordered = sorted(buckets.values(), key=lambda row: row["bucket"])
    return {"bucket_size": window.bucket_size, "buckets": ordered}


SECTION = Section("token_throughput", "Token throughput", compute)
