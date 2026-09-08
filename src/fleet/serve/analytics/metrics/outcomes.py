"""Outcome metrics: headline KPIs plus per-model and per-project tables.

Called by ``serve/analytics/summary.py`` (``SECTION``, ``BY_MODEL_SECTION``
and ``BY_PROJECT_SECTION`` join ``SUMMARY_SECTIONS``). Duration medians come
from ``metrics/timing.py`` and token sums from ``metrics/cost.py``.
"""

from __future__ import annotations

from fleet.serve.analytics.metrics import Section
from fleet.serve.analytics.metrics import cost as cost_metrics
from fleet.serve.analytics.metrics import timing as timing_metrics
from fleet.serve.analytics.records import AttemptRecord
from fleet.serve.analytics.window import Window, completed, in_window


def _windowed_completed(records: list[AttemptRecord], window: Window) -> list[AttemptRecord]:
    """Completions inside the window (active tasks never count here)."""
    return completed([record for record in records if in_window(record, window)])


def _headline_counts(records: list[AttemptRecord], done: list[AttemptRecord]) -> dict:
    """Completed/success/active/queued counts (latter two over all records)."""
    successes = sum(1 for record in done if record.outcome == "success")
    total = len(done)
    return {
        "completed": total,
        "success_rate": successes / total if total > 0 else 0.0,
        "active_now": sum(1 for r in records if r.status_reconciled == "in_progress"),
        "queued": sum(1 for r in records if r.status_reconciled in ("open", "ready")),
    }


def _duration_stats(done: list[AttemptRecord]) -> dict:
    """Median/p90 run seconds plus median queue wait over completions."""
    runs = [secs for record in done if (secs := timing_metrics.run_seconds(record)) is not None]
    waits = [
        secs for record in done if (secs := timing_metrics.queue_wait_seconds(record)) is not None
    ]
    return {
        "median_run_sec": timing_metrics.median(runs),
        "p90_run_sec": timing_metrics.percentile(sorted(runs), 90),
        "median_queue_wait_sec": timing_metrics.median(waits),
    }


def _volume_stats(done: list[AttemptRecord]) -> dict:
    """Steps, segments, errors and attention flags over completions."""
    segments = [record.segments for record in done]
    return {
        "total_steps": sum(record.steps for record in done),
        "avg_segments": sum(segments) / len(segments) if segments else 0.0,
        "error_events": sum(record.errors for record in done),
        "noclose_count": sum(1 for record in done if record.noclose),
        "rate_limited_tasks": sum(1 for record in done if record.rate_limited > 0),
    }


def compute(records: list[AttemptRecord], window: Window) -> dict:
    """Headline KPI dict over windowed completions (plus live active/queued)."""
    done = _windowed_completed(records, window)
    return {
        **_headline_counts(records, done),
        **_duration_stats(done),
        **cost_metrics.token_totals(done),
        **_volume_stats(done),
    }


def _model_accumulators(done: list[AttemptRecord]) -> dict[tuple[str, str], dict]:
    """Fold completions into per-(coder, model) accumulators."""
    agg: dict[tuple[str, str], dict] = {}
    for record in done:
        key = (record.coder or "unknown", record.model or "unknown")
        acc = agg.setdefault(
            key,
            {
                "total": 0,
                "successes": 0,
                "run_secs": [],
                "peak_ctx": [],
                "output_tokens": 0,
                "segments": [],
                "errors": 0,
                "rate_limited": 0,
            },
        )
        acc["total"] += 1
        if record.outcome == "success":
            acc["successes"] += 1
        if (secs := timing_metrics.run_seconds(record)) is not None:
            acc["run_secs"].append(secs)
        acc["output_tokens"] += record.output_tokens
        acc["segments"].append(record.segments)
        acc["errors"] += record.errors
        acc["rate_limited"] += 1 if record.rate_limited > 0 else 0
        if record.peak_context_tokens is not None:
            acc["peak_ctx"].append(record.peak_context_tokens)
    return agg


def _model_row(coder: str, model: str, acc: dict) -> dict:
    """Render one per-model breakdown row from its accumulator."""
    total = acc["total"]
    peaks = acc["peak_ctx"]
    segments = acc["segments"]
    return {
        "coder": coder,
        "model": model,
        "total": total,
        "success_rate": acc["successes"] / total if total else 0.0,
        "median_run_sec": timing_metrics.median(acc["run_secs"]),
        "mean_peak_context_tokens": sum(peaks) / len(peaks) if peaks else 0.0,
        "output_tokens": acc["output_tokens"],
        "avg_segments": sum(segments) / len(segments) if segments else 0.0,
        "errors": acc["errors"],
        "rate_limited": acc["rate_limited"],
    }


def compute_by_model(records: list[AttemptRecord], window: Window) -> list[dict]:
    """Per-(coder, model) rows over windowed completions, biggest first."""
    agg = _model_accumulators(_windowed_completed(records, window))
    rows = [_model_row(coder, model, acc) for (coder, model), acc in agg.items()]
    rows.sort(key=lambda row: row["total"], reverse=True)
    return rows


def _project_accumulators(done: list[AttemptRecord]) -> dict[str, dict]:
    """Fold completions into per-cwd accumulators."""
    agg: dict[str, dict] = {}
    for record in done:
        key = record.cwd or "unknown"
        acc = agg.setdefault(key, {"total": 0, "successes": 0, "run_secs": [], "output_tokens": 0})
        acc["total"] += 1
        if record.outcome == "success":
            acc["successes"] += 1
        if (secs := timing_metrics.run_seconds(record)) is not None:
            acc["run_secs"].append(secs)
        acc["output_tokens"] += record.output_tokens
    return agg


def _project_row(cwd: str, acc: dict) -> dict:
    """Render one per-project breakdown row from its accumulator."""
    total = acc["total"]
    return {
        "cwd": cwd,
        "total": total,
        "success_rate": acc["successes"] / total if total else 0.0,
        "median_run_sec": timing_metrics.median(acc["run_secs"]),
        "output_tokens": acc["output_tokens"],
    }


def compute_by_project(records: list[AttemptRecord], window: Window) -> list[dict]:
    """Per-cwd rows over windowed completions, biggest first."""
    agg = _project_accumulators(_windowed_completed(records, window))
    rows = [_project_row(cwd, acc) for cwd, acc in agg.items()]
    rows.sort(key=lambda row: row["total"], reverse=True)
    return rows


SECTION = Section("kpis", "Headline KPIs", compute)
BY_MODEL_SECTION = Section("by_model", "Outcomes by model", compute_by_model)
BY_PROJECT_SECTION = Section("by_project", "Outcomes by project", compute_by_project)
