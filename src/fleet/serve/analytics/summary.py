"""The /api/analytics/summary aggregator: on-the-fly stats from events.jsonl."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from fleet.beads import cache as beads_info
from fleet.beads.reconcile import merge_status
from fleet.coders import get_coder
from fleet.serve.analytics import records as records_module
from fleet.state.events import parse_iso
from fleet.state.task_summary import context_overrides_for_home

_HOURLY_BUCKET_MAX_DAYS = 3  # windows this short get hour buckets, longer ones day buckets
_CTX_PCT_FULL = 100
_CTX_PCT_HIGH = 75
_CTX_PCT_MID = 50
_CTX_PCT_LOW = 25
_DAYS_PER_WEEK = 7
_HOURS_PER_DAY = 24


def compute_summary(home: Path, days: int) -> dict:  # noqa: PLR0912, PLR0915  # ADR 0006 bead 10
    """Compute the /summary analytics endpoint data."""

    _context_overrides = context_overrides_for_home(home)
    # Clamp days
    clamped = 0 if days <= 0 else min(days, 365)

    # 1. Get records and beads map
    records = records_module.collect_records(home)
    beads = beads_info.get_beads_status_map(home)

    # 2. Reconcile each record
    reconciled = []
    for record in records:
        rid = record["id"]
        if beads is not None:
            merged = merge_status(record, beads.get(rid))
            r = dict(record)
            r["status_reconciled"] = merged["status"]
            r["created_at"] = merged["created_at"]
        else:
            r = dict(record)
            r["status_reconciled"] = r["status_raw"]
            r["created_at"] = None

        # 3. Outcome precedence
        status = r["status_reconciled"]
        if status == "closed":
            r["outcome"] = "success"
        elif status == "failed":
            r["outcome"] = "failed"
        elif status == "blocked":
            r["outcome"] = "blocked"
        else:
            r["outcome"] = "active"

        reconciled.append(r)

    now = datetime.now(tz=UTC)

    # 4. Window: completed = outcome in {success, failed, blocked} AND last_ts >= cutoff
    # Active records are never window-filtered
    cutoff = None if clamped == 0 else now - timedelta(days=clamped)

    windowed = []
    for r in reconciled:
        if r["outcome"] == "active":
            windowed.append(r)
            continue
        last_ts_str = r.get("last_ts")
        if last_ts_str and cutoff is not None:
            try:
                lt = parse_iso(last_ts_str)
                if lt is None:
                    windowed.append(r)
                    continue
                if lt < cutoff:
                    continue
            except (ValueError, TypeError):
                windowed.append(r)
                continue
        windowed.append(r)

    completed = [r for r in reconciled if r["outcome"] in ("success", "failed", "blocked")]
    completed_in_window = [r for r in windowed if r["outcome"] in ("success", "failed", "blocked")]

    # ---- KPIs ----
    n_completed = len(completed_in_window)
    n_success = sum(1 for r in completed_in_window if r["outcome"] == "success")
    success_rate = n_success / n_completed if n_completed > 0 else 0.0

    # active_now: reconciled status == "in_progress"
    active_now = sum(1 for r in reconciled if r["status_reconciled"] == "in_progress")
    # queued: status in {"open", "ready"}
    queued = sum(1 for r in reconciled if r["status_reconciled"] in ("open", "ready"))

    # Run times from windowed completed
    run_secs = []
    queue_secs = []
    for r in completed_in_window:
        last_ts_str = r.get("last_ts")
        first_ts_str = r.get("first_ts")
        if last_ts_str and first_ts_str:
            lt = parse_iso(last_ts_str)
            ft = parse_iso(first_ts_str)
            if lt and ft:
                run_secs.append((lt - ft).total_seconds())

        # Queue wait: reconciled created_at
        created = r.get("created_at")
        first = r.get("first_ts")
        if created and first:
            ca = parse_iso(created)
            f = parse_iso(first)
            if ca and f:
                diff = (f - ca).total_seconds()
                if diff >= 0:
                    queue_secs.append(diff)

    def _percentile(sorted_vals: list[float], p: float) -> float:
        """Compute percentile from a sorted list using linear interpolation."""
        n = len(sorted_vals)
        if n == 0:
            return 0.0
        if n == 1:
            return sorted_vals[0]
        rank = p / 100.0 * (n - 1)
        lo = int(rank)
        hi = lo + 1
        frac = rank - lo
        if hi >= n:
            return sorted_vals[-1]
        return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac

    def _median(vals: list[float]) -> float:
        sv = sorted(vals)
        return _percentile(sv, 50)

    run_secs_sorted = sorted(run_secs)
    median_run_sec = _percentile(run_secs_sorted, 50) if run_secs_sorted else 0.0
    p90_run_sec = _percentile(run_secs_sorted, 90) if run_secs_sorted else 0.0
    median_queue_wait_sec = _percentile(sorted(queue_secs), 50) if queue_secs else 0.0

    total_output_tokens = sum(r.get("output_tokens", 0) for r in completed_in_window)
    total_input_tokens = sum(r.get("input_tokens", 0) for r in completed_in_window)
    total_cache_read_tokens = sum(r.get("cache_read_tokens", 0) for r in completed_in_window)
    total_cache_creation_tokens = sum(
        r.get("cache_creation_tokens", 0) for r in completed_in_window
    )
    total_steps = sum(r.get("steps", 0) for r in completed_in_window)

    # avg_segments over completed
    segments_list = [r.get("segments", 0) for r in completed_in_window]
    avg_segments = sum(segments_list) / len(segments_list) if segments_list else 0.0

    # error_events: count of error event kinds across all completed,
    # using the per-task "errors" field from analytics.records
    error_events = sum(r.get("errors", 0) for r in completed_in_window)

    noclose_count = sum(1 for r in completed_in_window if r.get("noclose", False))

    rate_limited_tasks = sum(1 for r in completed_in_window if r.get("rate_limited", 0) > 0)

    kpis = {
        "completed": n_completed,
        "success_rate": success_rate,
        "active_now": active_now,
        "queued": queued,
        "median_run_sec": median_run_sec,
        "p90_run_sec": p90_run_sec,
        "median_queue_wait_sec": median_queue_wait_sec,
        "total_output_tokens": total_output_tokens,
        "total_input_tokens": total_input_tokens,
        "total_cache_read_tokens": total_cache_read_tokens,
        "total_cache_creation_tokens": total_cache_creation_tokens,
        "total_steps": total_steps,
        "avg_segments": avg_segments,
        "error_events": error_events,
        "noclose_count": noclose_count,
        "rate_limited_tasks": rate_limited_tasks,
    }

    # ---- Throughput ----
    if clamped == 0:
        bucket_size = "day"
    elif 1 <= clamped <= _HOURLY_BUCKET_MAX_DAYS:
        bucket_size = "hour"
    else:
        bucket_size = "day"

    throughput_buckets: dict[str, dict] = {}
    for r in completed_in_window:
        last_ts_str = r.get("last_ts")
        if not last_ts_str:
            continue
        lt = parse_iso(last_ts_str)
        if lt is None:
            continue

        if bucket_size == "hour":
            key = lt.replace(minute=0, second=0, microsecond=0).isoformat()
        else:
            key = lt.date().isoformat()

        if key not in throughput_buckets:
            throughput_buckets[key] = {
                "bucket": key,
                "success": 0,
                "failed": 0,
                "blocked": 0,
            }
        outcome_key = r["outcome"]  # success, failed, blocked
        if outcome_key in throughput_buckets[key]:
            throughput_buckets[key][outcome_key] += 1

    throughput = {
        "bucket_size": bucket_size,
        "buckets": sorted(throughput_buckets.values(), key=lambda b: b["bucket"]),
    }

    # ---- token_throughput: tokens per time bucket (same bucketing as throughput) ----
    token_buckets: dict[str, dict] = {}
    for r in completed_in_window:
        last_ts_str = r.get("last_ts")
        if not last_ts_str:
            continue
        lt = parse_iso(last_ts_str)
        if lt is None:
            continue
        if bucket_size == "hour":
            key = lt.replace(minute=0, second=0, microsecond=0).isoformat()
        else:
            key = lt.date().isoformat()
        if key not in token_buckets:
            token_buckets[key] = {
                "bucket": key,
                "output_tokens": 0,
                "input_tokens": 0,
                "cache_tokens": 0,
            }
        tb = token_buckets[key]
        tb["output_tokens"] += r.get("output_tokens", 0)
        tb["input_tokens"] += r.get("input_tokens", 0)
        tb["cache_tokens"] += r.get("cache_read_tokens", 0) + r.get("cache_creation_tokens", 0)

    token_throughput = {
        "bucket_size": bucket_size,
        "buckets": sorted(token_buckets.values(), key=lambda b: b["bucket"]),
    }

    # ---- by_model ----
    model_agg: dict[tuple[str, str], dict] = {}
    for r in completed_in_window:
        coder = r.get("coder") or "unknown"
        model = r.get("model") or "unknown"
        model_key = (coder, model)
        if model_key not in model_agg:
            model_agg[model_key] = {
                "total": 0,
                "successes": 0,
                "run_secs": [],
                "peak_ctx": [],
                "output_tokens": 0,
                "segments": [],
                "errors": 0,
                "rate_limited": 0,
            }
        a = model_agg[model_key]
        a["total"] += 1
        if r["outcome"] == "success":
            a["successes"] += 1
        last_ts_str = r.get("last_ts")
        first_ts_str = r.get("first_ts")
        if last_ts_str and first_ts_str:
            lt2 = parse_iso(last_ts_str)
            ft2 = parse_iso(first_ts_str)
            if lt2 and ft2:
                a["run_secs"].append((lt2 - ft2).total_seconds())
        a["output_tokens"] += r.get("output_tokens", 0)
        a["segments"].append(r.get("segments", 0))
        a["errors"] += r.get("errors", 0)
        a["rate_limited"] += 1 if r.get("rate_limited", 0) > 0 else 0
        ctx = r.get("peak_context_tokens")
        if ctx is not None:
            a["peak_ctx"].append(ctx)

    by_model_rows = []
    for (coder, model), a in model_agg.items():
        t = a["total"]
        by_model_rows.append(
            {
                "coder": coder,
                "model": model,
                "total": t,
                "success_rate": a["successes"] / t if t else 0.0,
                "median_run_sec": _percentile(sorted(a["run_secs"]), 50) if a["run_secs"] else 0.0,
                "mean_peak_context_tokens": sum(a["peak_ctx"]) / len(a["peak_ctx"])
                if a["peak_ctx"]
                else 0.0,
                "output_tokens": a["output_tokens"],
                "avg_segments": sum(a["segments"]) / len(a["segments"]) if a["segments"] else 0.0,
                "errors": a["errors"],
                "rate_limited": a["rate_limited"],
            }
        )
    by_model_rows.sort(key=lambda x: x["total"], reverse=True)

    # ---- by_project ----
    proj_agg: dict[str, dict] = {}
    for r in completed_in_window:
        cwd = r.get("cwd") or "unknown"
        if cwd not in proj_agg:
            proj_agg[cwd] = {
                "total": 0,
                "successes": 0,
                "run_secs": [],
                "output_tokens": 0,
            }
        a = proj_agg[cwd]
        a["total"] += 1
        if r["outcome"] == "success":
            a["successes"] += 1
        last_ts_str = r.get("last_ts")
        first_ts_str = r.get("first_ts")
        if last_ts_str and first_ts_str:
            lt2 = parse_iso(last_ts_str)
            ft2 = parse_iso(first_ts_str)
            if lt2 and ft2:
                a["run_secs"].append((lt2 - ft2).total_seconds())
        a["output_tokens"] += r.get("output_tokens", 0)

    by_project_rows = []
    for cwd, a in proj_agg.items():
        t = a["total"]
        by_project_rows.append(
            {
                "cwd": cwd,
                "total": t,
                "success_rate": a["successes"] / t if t else 0.0,
                "median_run_sec": _percentile(sorted(a["run_secs"]), 50) if a["run_secs"] else 0.0,
                "output_tokens": a["output_tokens"],
            }
        )
    by_project_rows.sort(key=lambda x: x["total"], reverse=True)

    # ---- tools: merge tool_counts across in-window records (completed + active) ----
    all_tool_counts: dict[str, int] = {}
    for r in windowed:
        tc = r.get("tool_counts") or {}
        for tn, cnt in tc.items():
            all_tool_counts[tn] = all_tool_counts.get(tn, 0) + cnt
    total_tools = sum(all_tool_counts.values())
    rows_tools = sorted(
        [{"name": name, "count": count} for name, count in all_tool_counts.items()],
        key=lambda x: x["count"],  # type: ignore[arg-type, return-value]  # untyped rows; bead 10 adds metric models
        reverse=True,
    )[:20]
    tools = {"total": total_tools, "rows": rows_tools}

    # ---- context_histogram: buckets based on peak_context_tokens / context_limit ----
    _HIST_BUCKETS_COUNTS: dict[str, int] = {
        "0-25": 0,
        "25-50": 0,
        "50-75": 0,
        "75-100": 0,
        "100+": 0,
    }
    for r in completed:
        pct = r.get("peak_context_tokens")
        if pct is None:
            continue
        coder = r.get("coder") or ""
        try:
            limit = get_coder(coder).context_limit_for(r.get("model"), _context_overrides)
        except (ValueError, TypeError, IndexError):
            limit = 200_000
        if limit <= 0:
            limit = 200_000
        ratio = (pct / limit) * 100
        ratio = max(ratio, 0)
        if ratio >= _CTX_PCT_FULL:
            _HIST_BUCKETS_COUNTS["100+"] += 1
        elif ratio >= _CTX_PCT_HIGH:
            _HIST_BUCKETS_COUNTS["75-100"] += 1
        elif ratio >= _CTX_PCT_MID:
            _HIST_BUCKETS_COUNTS["50-75"] += 1
        elif ratio >= _CTX_PCT_LOW:
            _HIST_BUCKETS_COUNTS["25-50"] += 1
        else:
            _HIST_BUCKETS_COUNTS["0-25"] += 1
    context_histogram = {"buckets": _HIST_BUCKETS_COUNTS}

    # ---- heatmap: 7x24 matrix summed across in-window records ----
    heatmap = [[0] * _HOURS_PER_DAY for _ in range(_DAYS_PER_WEEK)]
    for r in windowed:
        hh = r.get("hour_hist") or {}
        for key, val in hh.items():
            try:
                parts = key.split("-")
                wd = int(parts[0])
                hr = int(parts[1])
                if 0 <= wd < _DAYS_PER_WEEK and 0 <= hr < _HOURS_PER_DAY:
                    heatmap[wd][hr] += val
            except (ValueError, IndexError):
                pass
    sum(sum(row) for row in heatmap)

    # ---- errors_recent: up to 10 completed tasks needing attention, newest
    # last_ts first. failed/blocked outcomes come labeled as-is; tasks that
    # closed but hit a problem flag are included labeled by the flag.
    def _attention_label(r: dict) -> str | None:
        if r["outcome"] in ("failed", "blocked"):
            return r["outcome"]
        if r.get("noclose"):
            return "noclose"
        if r.get("context_pressure"):
            return "context_pressure"
        if r.get("rate_limited", 0) > 0:
            return "rate_limited"
        return None

    errors_candidates = [
        (r, label) for r in completed if (label := _attention_label(r)) is not None
    ]
    errors_candidates.sort(
        key=lambda pair: pair[0].get("last_ts") or "",
        reverse=True,
    )
    errors_recent = []
    for r, label in errors_candidates[:10]:
        errors_recent.append(
            {
                "id": r["id"],
                "title": r.get("title", ""),
                "coder": r.get("coder", "unknown"),
                "model": r.get("model", "unknown"),
                "outcome": label,
                "ended_at": r.get("last_ts", ""),
            }
        )

    # ---- rate_limits: flat list from rate_limit_events of in-window completed+active ----
    _rl_events: list[dict] = []
    for r in windowed:
        for ts in r.get("rate_limit_events") or []:
            _rl_events.append({"ts": ts, "task_id": r["id"]})
    _rl_events.sort(key=lambda e: e["ts"])
    rate_limits = _rl_events

    return {
        "window_days": clamped,
        "kpis": kpis,
        "throughput": throughput,
        "token_throughput": token_throughput,
        "by_model": by_model_rows,
        "by_project": by_project_rows,
        "tools": tools,
        "context_histogram": context_histogram,
        "heatmap": heatmap,
        "errors_recent": errors_recent,
        "rate_limits": rate_limits,
    }
