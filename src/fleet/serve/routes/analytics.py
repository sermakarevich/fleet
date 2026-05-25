"""On-the-fly analytics from events.jsonl (FR-35, FR-36, FR-37, FR-38, FR-39, FR-40, FR-41)."""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from fleet.serve.stats import fleet_home as get_fleet_home, task_runtime_stats


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


def _scan_events(task_dir: Path) -> tuple[
    list[dict],   # all parsed events
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

    # Blocked: check if blocked_by_agent (has ask_human extra events)
    for ev in events:
        extra = ev.get("extra") or {}
        if extra.get("kind") == "ask_human":
            return "blocked_by_agent"

    return "failure"


def create_analytics_router() -> APIRouter:
    router = APIRouter(prefix="/api/analytics")

    @router.get("/throughput")
    async def get_throughput() -> JSONResponse:
        home = get_fleet_home()
        now = datetime.now(tz=timezone.utc)
        cutoff = now - timedelta(days=7)

        # bucket_key → {success, failure, rate_limit, context_pressure, blocked_by_agent}
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

            # Truncate to hour
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

        return JSONResponse({"buckets": sorted(buckets.values(), key=lambda b: b["hour"])})

    @router.get("/leaderboard")
    async def get_leaderboard() -> JSONResponse:
        home = get_fleet_home()

        # (coder, model) → {successes, total, elapsed_secs, tokens, qa_count}
        agg: dict[tuple[str, str], dict] = defaultdict(lambda: {
            "successes": 0, "total": 0,
            "elapsed_secs": [], "tokens": [], "qa_count": 0,
        })

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

            has_qa = any(
                (ev.get("extra") or {}).get("kind") == "ask_human"
                for ev in events
            )
            if has_qa:
                agg[key]["qa_count"] += 1

        rows = []
        for (coder, model), d in sorted(agg.items()):
            total = d["total"]
            elapsed_list = d["elapsed_secs"]
            token_list = d["tokens"]
            rows.append({
                "coder": coder,
                "model": model,
                "success_rate": d["successes"] / total if total else 0.0,
                "mean_elapsed_sec": sum(elapsed_list) / len(elapsed_list) if elapsed_list else 0.0,
                "mean_tokens": sum(token_list) / len(token_list) if token_list else 0.0,
                "qa_rate": d["qa_count"] / total if total else 0.0,
            })

        return JSONResponse({"rows": rows})

    @router.get("/burnouts")
    async def get_burnouts() -> JSONResponse:
        home = get_fleet_home()

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
            {"coder": c, "model": m, "count": n}
            for (c, m), n in sorted(counts.items())
        ]
        return JSONResponse({"rows": rows})

    @router.get("/rate-limits")
    async def get_rate_limits() -> JSONResponse:
        home = get_fleet_home()

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
                # Try to get provider from rate_info
                provider = rate_info.get("provider") or "unknown"
                events_out.append({
                    "ts": ts,
                    "provider": provider,
                    "duration_sec": duration_sec,
                })

        events_out.sort(key=lambda e: e["ts"])
        return JSONResponse({"events": events_out})

    @router.get("/per-project")
    async def get_per_project() -> JSONResponse:
        home = get_fleet_home()

        agg: dict[str, dict] = defaultdict(lambda: {
            "total": 0, "successes": 0, "elapsed_secs": [],
        })

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
            rows.append({
                "cwd": cwd,
                "task_count": total,
                "success_rate": d["successes"] / total if total else 0.0,
                "mean_elapsed_sec": sum(elapsed_list) / len(elapsed_list) if elapsed_list else 0.0,
            })

        return JSONResponse({"rows": rows})

    return router
