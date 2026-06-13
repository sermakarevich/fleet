"""Cached per-task analytics record extractor.

Mirrors the cache strategy in ``stats.task_runtime_info_cached``: module-level
dict keyed by task-dir string, invalidated when events.jsonl mtime or size
changes.  Re-uses ``parse_iso`` and ``_safe_int`` from stats.py.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .stats import parse_iso


# Cache: tdir_str -> (events.jsonl mtime, events.jsonl size, task_record dict)
# (-1.0, -1) sentinel when events.jsonl is absent.
_info_cache: dict[str, tuple[float, int, dict]] = {}


def _safe_int(v: object) -> int:
    if isinstance(v, bool):
        return 0
    if isinstance(v, int):
        return v
    if isinstance(v, str):
        try:
            return int(v)
        except ValueError:
            return 0
    return 0


def task_record_cached(tdir: Path) -> dict:
    """Return a dict of analytics records for *tdir* with file-change cache.

    Re-scans only when events.jsonl mtime or size changes from the last call.
    When events.jsonl is absent the sentinel ``(-1.0, -1)`` is cached.
    """
    events_file = tdir / "events.jsonl"
    cache_key = str(tdir)

    try:
        st = events_file.stat()
        file_mtime: float = st.st_mtime
        file_size: int = st.st_size
    except OSError:
        file_mtime, file_size = -1.0, -1

    entry = _info_cache.get(cache_key)
    if entry is not None and entry[0] == file_mtime and entry[1] == file_size:
        return entry[2]

    result = _build_record(tdir, events_file)
    _info_cache[cache_key] = (file_mtime, file_size, result)
    return result


def _str_to_iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt is not None else None


def _build_record(tdir: Path, events_file: Path) -> dict:
    """Single-pass build of the record (no cache)."""
    task_json_file = tdir / "task.json"
    title = ""
    coder = ""
    model = ""
    cwd = ""
    priority = 0
    status_raw = ""
    try:
        with task_json_file.open("r", encoding="utf-8") as fh:
            task_data = json.load(fh)
        title = task_data.get("title", "")
        coder = task_data.get("coder", "")
        model = task_data.get("model", "")
        cwd = task_data.get("cwd", "")
        priority = task_data.get("priority", 0)
        status_raw = task_data.get("status", "")
    except (OSError, json.JSONDecodeError):
        pass

    tdir_name = tdir.name
    id_ = tdir_name if tdir_name else ""

    first_ts: datetime | None = None
    last_ts: datetime | None = None
    events_count = 0
    steps = 0
    segments_set: set[str] = set()
    errors = 0
    tool_counts: dict[str, int] = {}
    output_tokens = 0
    peak_context_tokens: int | None = None
    rate_limited = 0
    rate_limit_events_ts: list[str] = []
    hour_hist: dict[str, int] = {}
    has_context_pressure_event = False

    if events_file.exists():
        try:
            with events_file.open("r", encoding="utf-8") as fh:
                for raw_line in fh:
                    line = raw_line.strip()
                    if not line:
                        continue
                    events_count += 1
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        events_count -= 1
                        continue

                    ts_str = row.get("ts")
                    ts_dt: datetime | None = None
                    if isinstance(ts_str, str):
                        ts_dt = parse_iso(ts_str)

                    kind = row.get("kind")

                    # first/last parseable ts
                    if ts_dt is not None:
                        if first_ts is None or ts_dt < first_ts:
                            first_ts = ts_dt
                        if last_ts is None or ts_dt > last_ts:
                            last_ts = ts_dt

                    # steps
                    if kind == "session_started":
                        steps += 1

                    # segments (distinct non-null session_id)
                    sid = row.get("session_id")
                    if sid is not None:
                        segments_set.add(sid)

                    # errors
                    if kind == "error":
                        errors += 1

                    # tool_counts
                    if kind == "tool_result":
                        tn = row.get("tool_name")
                        if tn is not None:
                            tool_counts[tn] = tool_counts.get(tn, 0) + 1

                    # output_tokens (exclude session_ended)
                    if kind != "session_ended":
                        usage = row.get("usage")
                        if isinstance(usage, dict):
                            output_tokens += _safe_int(usage.get("output_tokens"))

                    # peak_context_tokens (exclude session_ended)
                    if kind != "session_ended":
                        usage = row.get("usage")
                        if isinstance(usage, dict):
                            ctx = (
                                _safe_int(usage.get("input_tokens"))
                                + _safe_int(usage.get("cache_creation_input_tokens"))
                                + _safe_int(usage.get("cache_read_input_tokens"))
                            )
                            if ctx > 0:
                                peak_context_tokens = (
                                    ctx
                                    if peak_context_tokens is None
                                    else max(peak_context_tokens, ctx)
                                )

                    # rate_limit_info events
                    rate_info = row.get("rate_info")
                    if kind in ("rate_limit", "rate_limit_info") and isinstance(
                        rate_info, dict
                    ):
                        if rate_info.get("status") == "rejected":
                            rate_limited += 1
                            if ts_str is not None:
                                rate_limit_events_ts.append(ts_str)

                    # hour_hist
                    if ts_dt is not None:
                        key = f"{ts_dt.weekday()}-{ts_dt.hour}"
                        hour_hist[key] = hour_hist.get(key, 0) + 1

                    # context_pressure event kind
                    if kind == "context_pressure":
                        has_context_pressure_event = True
        except OSError:
            pass

    context_pressure = (
        tdir / ".context_pressure"
    ).exists() or has_context_pressure_event
    noclose = (tdir / ".noclose").exists()

    record = {
        "id": id_,
        "title": title,
        "coder": coder,
        "model": model,
        "cwd": cwd,
        "priority": priority,
        "status_raw": status_raw,
        "first_ts": _str_to_iso(first_ts),
        "last_ts": _str_to_iso(last_ts),
        "events": events_count,
        "steps": steps,
        "segments": len(segments_set),
        "errors": errors,
        "tool_counts": tool_counts,
        "output_tokens": output_tokens,
        "peak_context_tokens": peak_context_tokens,
        "rate_limited": rate_limited,
        "rate_limit_events": rate_limit_events_ts,
        "context_pressure": context_pressure,
        "noclose": noclose,
        "hour_hist": hour_hist,
    }

    return record


def collect_records(home: Path) -> list[dict]:
    """For every <home>/tasks/*/ dir containing task.json, return task_record.

    Skips dirs that do not contain a task.json file.
    """
    tasks_dir = home / "tasks"
    results: list[dict] = []
    if not tasks_dir.exists():
        return results
    for task_dir_path in sorted(tasks_dir.iterdir()):
        if not task_dir_path.is_dir():
            continue
        if not (task_dir_path / "task.json").exists():
            continue
        results.append(task_record_cached(task_dir_path))
    return results
