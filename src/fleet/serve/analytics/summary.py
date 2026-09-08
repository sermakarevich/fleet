"""The /api/analytics/summary aggregator: registry plus thin entry point.

Called by ``serve/api/analytics.py`` (``compute_summary``). Per-family math
lives in ``serve/analytics/metrics/*``; this module owns the
``SUMMARY_SECTIONS`` registry, the ``summarize`` dispatch, and the
beads-reconciliation step that turns raw records into decided outcomes.
"""

from __future__ import annotations

from dataclasses import asdict, replace
from pathlib import Path

from fleet.beads import cache as beads_info
from fleet.beads.reconcile import merge_status
from fleet.serve.analytics import records as records_module
from fleet.serve.analytics.metrics import Section
from fleet.serve.analytics.metrics import attention as attention_metrics
from fleet.serve.analytics.metrics import context as context_metrics
from fleet.serve.analytics.metrics import cost as cost_metrics
from fleet.serve.analytics.metrics import outcomes as outcomes_metrics
from fleet.serve.analytics.metrics import throughput as throughput_metrics
from fleet.serve.analytics.metrics import timing as timing_metrics
from fleet.serve.analytics.metrics import tools as tools_metrics
from fleet.serve.analytics.records import AttemptRecord
from fleet.serve.analytics.window import Window, build_window

#: Outcome by reconciled status; anything else is still active.
OUTCOME_BY_STATUS = {"closed": "success", "failed": "failed", "blocked": "blocked"}

#: Every metric in response order; summarize renders one key per section.
SUMMARY_SECTIONS: list[Section] = [
    outcomes_metrics.SECTION,
    throughput_metrics.SECTION,
    cost_metrics.SECTION,
    outcomes_metrics.BY_MODEL_SECTION,
    outcomes_metrics.BY_PROJECT_SECTION,
    tools_metrics.SECTION,
    context_metrics.SECTION,
    timing_metrics.SECTION,
    attention_metrics.SECTION,
    attention_metrics.RATE_LIMITS_SECTION,
]


def summarize(records: list[AttemptRecord], window: Window) -> dict:
    """Render every registry section over reconciled *records*."""
    return {section.key: section.compute(records, window) for section in SUMMARY_SECTIONS}


def _reconcile_one(record: AttemptRecord, beads: dict | None) -> AttemptRecord:
    """Merge one record against the beads map and decide its outcome."""
    if beads is not None:
        merged = merge_status(asdict(record), beads.get(record.id))
        status = merged["status"]
        created_at = merged["created_at"]
    else:
        status = record.status_raw
        created_at = None
    return replace(
        record,
        status_reconciled=status,
        created_at=created_at,
        outcome=OUTCOME_BY_STATUS.get(status, "active"),
    )


def reconcile(records: list[AttemptRecord], beads: dict[str, dict] | None) -> list[AttemptRecord]:
    """Reconcile every record against the beads map (None skips merging)."""
    return [_reconcile_one(record, beads) for record in records]


def compute_summary(home: Path, days: int) -> dict:
    """Compute the /summary analytics endpoint data."""
    records = records_module.collect_records(home)
    beads = beads_info.get_beads_status_map(home)
    window = build_window(home, days)
    return {"window_days": window.days, **summarize(reconcile(records, beads), window)}
