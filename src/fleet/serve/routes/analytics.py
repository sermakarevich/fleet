"""On-the-fly analytics from events.jsonl (FR-35, FR-36, FR-37, FR-38, FR-39, FR-40, FR-41)."""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from fleet.coders import get_coder
from fleet.serve import analytics_core as _ac
from fleet.serve import beads_info as _bi
from fleet.serve.stats import (
    fleet_home as get_fleet_home,
    parse_iso,
    task_runtime_stats,
)


def _iter_task_dirs(home: Path):
    tasks_dir = home / "tasks"
    if not tasks_dir.is_dir():
        return
    for task_dir in tasks_dir.iterdir():
        if task_dir.is_dir():
            yield task_dir


def _read_task_json(task_dir: Path) -> dict:
    f = task_dir / "task.json"
    if not f.exists():
        return {}
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _scan_events(
    task_dir: Path,
) -> tuple[
    list[dict],  # all parsed events
    datetime | None,  # first event ts
    datetime | None,  # last event ts
]:
    events_file = task_dir / "events.jsonl"
    if not events_file.exists():
        return [], None, None
    events = []
    first_ts: datetime | None = None
    last_ts: datetime | None = None
    try:
        with events_file.open("r", encoding="utf-8") as fh:
            for raw in fh:
                line = raw.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                events.append(row)
                ts_str = row.get("ts")
                if isinstance(ts_str, str):
                    try:
                        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                        if first_ts is None:
                            first_ts = ts
                        last_ts = ts
                    except ValueError:
                        pass
    except OSError:
        pass
    return events, first_ts, last_ts


def _classify_outcome(task_json: dict, events: list[dict], task_dir: Path) -> str:
    status = task_json.get("status", "")
    if status not in ("closed", "blocked"):
        return "active"

    # Check for rate_limit
    for ev in events:
        if ev.get("kind") == "rate_limit":
            rate_info = ev.get("rate_info") or {}
            if rate_info.get("status") == "rejected":
                return "rate_limit"

    # Check for context_pressure
    if (task_dir / ".context_pressure").exists():
        return "context_pressure"
    for ev in events:
        if ev.get("kind") == "context_pressure":
            return "context_pressure"

    if status == "closed":
        return "success"

    return "failure"


def _compute_throughput(home: Path) -> dict:
    now = datetime.now(tz=timezone.utc)
    cutoff = now - timedelta(days=7)
    buckets: dict[str, dict[str, int]] = {}
    for task_dir in _iter_task_dirs(home):
        task_json = _read_task_json(task_dir)
        if not task_json:
            continue
        events, first_ts, last_ts = _scan_events(task_dir)
        outcome = _classify_outcome(task_json, events, task_dir)
        if outcome == "active":
            continue
        completion_ts = last_ts or first_ts
        if completion_ts is None or completion_ts < cutoff:
            continue
        hour = completion_ts.replace(minute=0, second=0, microsecond=0)
        key = hour.isoformat()
        if key not in buckets:
            buckets[key] = {
                "hour": key,
                "success": 0,
                "failure": 0,
                "rate_limit": 0,
                "context_pressure": 0,
                "blocked_by_agent": 0,
            }
        buckets[key][outcome] = buckets[key].get(outcome, 0) + 1
    return {"buckets": sorted(buckets.values(), key=lambda b: b["hour"])}


def _compute_leaderboard(home: Path) -> dict:
    agg: dict[tuple[str, str], dict] = defaultdict(
        lambda: {
            "successes": 0,
            "total": 0,
            "elapsed_secs": [],
            "tokens": [],
        }
    )
    for task_dir in _iter_task_dirs(home):
        task_json = _read_task_json(task_dir)
        if not task_json:
            continue
        coder = task_json.get("coder") or "unknown"
        model = task_json.get("model") or "unknown"
        events, first_ts, last_ts = _scan_events(task_dir)
        outcome = _classify_outcome(task_json, events, task_dir)
        if outcome == "active":
            continue
        key = (coder, model)
        agg[key]["total"] += 1
        if outcome == "success":
            agg[key]["successes"] += 1
        if first_ts and last_ts and last_ts > first_ts:
            agg[key]["elapsed_secs"].append((last_ts - first_ts).total_seconds())
        stats = task_runtime_stats(task_dir.name)
        if stats.context_tokens is not None:
            agg[key]["tokens"].append(stats.context_tokens)
    rows = []
    for (coder, model), d in sorted(agg.items()):
        total = d["total"]
        elapsed_list = d["elapsed_secs"]
        token_list = d["tokens"]
        rows.append(
            {
                "coder": coder,
                "model": model,
                "success_rate": d["successes"] / total if total else 0.0,
                "mean_elapsed_sec": sum(elapsed_list) / len(elapsed_list)
                if elapsed_list
                else 0.0,
                "mean_tokens": sum(token_list) / len(token_list) if token_list else 0.0,
            }
        )
    return {"rows": rows}


def _compute_burnouts(home: Path) -> dict:
    counts: dict[tuple[str, str], int] = defaultdict(int)
    for task_dir in _iter_task_dirs(home):
        task_json = _read_task_json(task_dir)
        if not task_json:
            continue
        events, _, _ = _scan_events(task_dir)
        is_cp = (task_dir / ".context_pressure").exists() or any(
            ev.get("kind") == "context_pressure" for ev in events
        )
        if not is_cp:
            continue
        coder = task_json.get("coder") or "unknown"
        model = task_json.get("model") or "unknown"
        counts[(coder, model)] += 1
    rows = [
        {"coder": c, "model": m, "count": n} for (c, m), n in sorted(counts.items())
    ]
    return {"rows": rows}


def _compute_rate_limits(home: Path) -> dict:
    events_out = []
    for task_dir in _iter_task_dirs(home):
        events, _, _ = _scan_events(task_dir)
        for ev in events:
            if ev.get("kind") != "rate_limit":
                continue
            rate_info = ev.get("rate_info") or {}
            if rate_info.get("status") != "rejected":
                continue
            ts = ev.get("ts", "")
            resets_at = rate_info.get("resets_at")
            duration_sec: float | None = None
            if resets_at is not None and ts:
                try:
                    ts_dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    duration_sec = resets_at - ts_dt.timestamp()
                except (ValueError, TypeError):
                    pass
            provider = rate_info.get("provider") or "unknown"
            events_out.append(
                {
                    "ts": ts,
                    "provider": provider,
                    "duration_sec": duration_sec,
                }
            )
    events_out.sort(key=lambda e: e["ts"])
    return {"events": events_out}


def _compute_per_project(home: Path) -> dict:
    agg: dict[str, dict] = defaultdict(
        lambda: {
            "total": 0,
            "successes": 0,
            "elapsed_secs": [],
        }
    )
    for task_dir in _iter_task_dirs(home):
        task_json = _read_task_json(task_dir)
        if not task_json:
            continue
        cwd = task_json.get("cwd") or "unknown"
        events, first_ts, last_ts = _scan_events(task_dir)
        outcome = _classify_outcome(task_json, events, task_dir)
        if outcome == "active":
            continue
        agg[cwd]["total"] += 1
        if outcome == "success":
            agg[cwd]["successes"] += 1
        if first_ts and last_ts and last_ts > first_ts:
            agg[cwd]["elapsed_secs"].append((last_ts - first_ts).total_seconds())
    rows = []
    for cwd, d in sorted(agg.items()):
        total = d["total"]
        elapsed_list = d["elapsed_secs"]
        rows.append(
            {
                "cwd": cwd,
                "task_count": total,
                "success_rate": d["successes"] / total if total else 0.0,
                "mean_elapsed_sec": sum(elapsed_list) / len(elapsed_list)
                if elapsed_list
                else 0.0,
            }
        )
    return {"rows": rows}


def _compute_summary(home: Path, days: int) -> dict:
    """Compute the /summary analytics endpoint data."""
    # Clamp days
    if days <= 0:
        clamped = 0
    else:
        clamped = min(days, 365)

    # 1. Get records and beads map
    records = _ac.collect_records(home)
    beads = _bi.get_beads_status_map(home)

    # 2. Reconcile each record
    reconciled = []
    for r in records:
        rid = r["id"]
        beads_status = None
        beads_created = None
        if beads is not None and rid in beads:
            beads_status = beads[rid].get("status", "open")
            beads_created = beads[rid].get("created_at")
        elif beads is not None and rid not in beads:
            beads_status = "closed"
            beads_created = None

        if beads_status is not None:
            r = dict(r)
            r["status_reconciled"] = beads_status
            # Use beads created_at for reconciled records
            r["created_at"] = beads_created
        else:
            r = dict(r)
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

    now = datetime.now(tz=timezone.utc)

    # 4. Window: completed = outcome in {success, failed, blocked} AND last_ts >= cutoff
    # Active records are never window-filtered
    if clamped == 0:
        cutoff = None
    else:
        cutoff = now - timedelta(days=clamped)

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

    completed = [
        r for r in reconciled if r["outcome"] in ("success", "failed", "blocked")
    ]
    completed_in_window = [
        r for r in windowed if r["outcome"] in ("success", "failed", "blocked")
    ]

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
    total_cache_read_tokens = sum(
        r.get("cache_read_tokens", 0) for r in completed_in_window
    )
    total_cache_creation_tokens = sum(
        r.get("cache_creation_tokens", 0) for r in completed_in_window
    )
    total_steps = sum(r.get("steps", 0) for r in completed_in_window)

    # avg_segments over completed
    segments_list = [r.get("segments", 0) for r in completed_in_window]
    avg_segments = sum(segments_list) / len(segments_list) if segments_list else 0.0

    # error_events: count of error event kinds across all completed
    # We use the stored r["errors"] field from analytics_core
    error_events = sum(r.get("errors", 0) for r in completed_in_window)

    noclose_count = sum(1 for r in completed_in_window if r.get("noclose", False))

    rate_limited_tasks = sum(
        1 for r in completed_in_window if r.get("rate_limited", 0) > 0
    )

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
    elif 1 <= clamped <= 3:
        bucket_size = "hour"
    else:
        bucket_size = "day"

    throughput_buckets: dict[str, dict[str, int]] = {}
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
        tb["cache_tokens"] += r.get("cache_read_tokens", 0) + r.get(
            "cache_creation_tokens", 0
        )

    token_throughput = {
        "bucket_size": bucket_size,
        "buckets": sorted(token_buckets.values(), key=lambda b: b["bucket"]),
    }

    # ---- by_model ----
    model_agg: dict[tuple[str, str], dict] = {}
    for r in completed_in_window:
        coder = r.get("coder") or "unknown"
        model = r.get("model") or "unknown"
        key = (coder, model)
        if key not in model_agg:
            model_agg[key] = {
                "total": 0,
                "successes": 0,
                "run_secs": [],
                "peak_ctx": [],
                "output_tokens": 0,
                "segments": [],
                "errors": 0,
                "rate_limited": 0,
            }
        a = model_agg[key]
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
                "median_run_sec": _percentile(sorted(a["run_secs"]), 50)
                if a["run_secs"]
                else 0.0,
                "mean_peak_context_tokens": sum(a["peak_ctx"]) / len(a["peak_ctx"])
                if a["peak_ctx"]
                else 0.0,
                "output_tokens": a["output_tokens"],
                "avg_segments": sum(a["segments"]) / len(a["segments"])
                if a["segments"]
                else 0.0,
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
                "median_run_sec": _percentile(sorted(a["run_secs"]), 50)
                if a["run_secs"]
                else 0.0,
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
        key=lambda x: x["count"],
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
            limit = get_coder(coder).context_limit
        except (ValueError, TypeError, IndexError):
            limit = 200_000
        if limit <= 0:
            limit = 200_000
        ratio = (pct / limit) * 100
        if ratio < 0:
            ratio = 0
        if ratio >= 100:
            _HIST_BUCKETS_COUNTS["100+"] += 1
        elif ratio >= 75:
            _HIST_BUCKETS_COUNTS["75-100"] += 1
        elif ratio >= 50:
            _HIST_BUCKETS_COUNTS["50-75"] += 1
        elif ratio >= 25:
            _HIST_BUCKETS_COUNTS["25-50"] += 1
        else:
            _HIST_BUCKETS_COUNTS["0-25"] += 1
    context_histogram = {"buckets": _HIST_BUCKETS_COUNTS}

    # ---- heatmap: 7x24 matrix summed across in-window records ----
    heatmap = [[0] * 24 for _ in range(7)]
    for r in windowed:
        hh = r.get("hour_hist") or {}
        for key, val in hh.items():
            try:
                parts = key.split("-")
                wd = int(parts[0])
                hr = int(parts[1])
                if 0 <= wd < 7 and 0 <= hr < 24:
                    heatmap[wd][hr] += val
            except (ValueError, IndexError):
                pass
    heatmap_sum = sum(sum(row) for row in heatmap)

    # ---- errors_recent: up to 10 completed failed/blocked, newest last_ts first ----
    errors_candidates = [r for r in completed if r["outcome"] in ("failed", "blocked")]
    errors_candidates.sort(
        key=lambda r: r.get("last_ts") or "",
        reverse=True,
    )
    errors_recent = []
    for r in errors_candidates[:10]:
        errors_recent.append(
            {
                "id": r["id"],
                "title": r.get("title", ""),
                "coder": r.get("coder", "unknown"),
                "model": r.get("model", "unknown"),
                "outcome": r["outcome"],
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


def create_analytics_router() -> APIRouter:
    router = APIRouter(prefix="/api/analytics")

    @router.get("/throughput")
    async def get_throughput() -> JSONResponse:
        """Deprecated: superseded by /summary."""
        return JSONResponse(
            await asyncio.to_thread(_compute_throughput, get_fleet_home())
        )

    @router.get("/leaderboard")
    async def get_leaderboard() -> JSONResponse:
        """Deprecated: superseded by /summary."""
        return JSONResponse(
            await asyncio.to_thread(_compute_leaderboard, get_fleet_home())
        )

    @router.get("/burnouts")
    async def get_burnouts() -> JSONResponse:
        """Deprecated: superseded by /summary."""
        return JSONResponse(
            await asyncio.to_thread(_compute_burnouts, get_fleet_home())
        )

    @router.get("/rate-limits")
    async def get_rate_limits() -> JSONResponse:
        """Deprecated: superseded by /summary."""
        return JSONResponse(
            await asyncio.to_thread(_compute_rate_limits, get_fleet_home())
        )

    @router.get("/per-project")
    async def get_per_project() -> JSONResponse:
        """Deprecated: superseded by /summary."""
        return JSONResponse(
            await asyncio.to_thread(_compute_per_project, get_fleet_home())
        )

    @router.get("/summary")
    async def get_summary(days: int = 7) -> JSONResponse:
        return JSONResponse(
            await asyncio.to_thread(_compute_summary, get_fleet_home(), days)
        )

    return router
