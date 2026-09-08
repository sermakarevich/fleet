"""Cached per-task analytics record extractor.

Builds one dict per task by combining task.json metadata with the shared
``state.events`` scan of events.jsonl.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from fleet.state.events import scan_cached


def _str_to_iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt is not None else None


def _build_record(tdir: Path) -> dict:
    task_json_file = tdir / "task.json"
    title = ""
    coder = ""
    model = ""
    cwd = ""
    priority = 0
    status_raw = ""
    created_at = None
    try:
        with task_json_file.open("r", encoding="utf-8") as fh:
            task_data = json.load(fh)
        title = task_data.get("title", "")
        coder = task_data.get("coder", "")
        model = task_data.get("model", "")
        cwd = task_data.get("cwd", "")
        priority = task_data.get("priority", 0)
        status_raw = task_data.get("status", "")
        created_at = task_data.get("created_at")
    except (OSError, json.JSONDecodeError):
        pass

    id_ = tdir.name or ""
    stats = scan_cached(tdir)

    context_pressure = (tdir / ".context_pressure").exists() or stats.context_pressure
    try:
        from fleet.state.attempts import load_attempts

        _history = load_attempts(tdir)
        _last = _history[-1] if _history else {}
        noclose = _last.get("outcome") in ("success", "partial") and _last.get("action") in (
            "release",
            "released",
            None,
        )
        # load_attempts merges start/end rows; an unfinished latest attempt has
        # outcome None. Fall back to the outcome-bearing tail in that case.
        if _last.get("outcome") is None:
            noclose = any(
                h.get("outcome") in ("success", "partial") for h in _history[-3:]
            )
    except Exception:
        noclose = False

    return {
        "id": id_,
        "title": title,
        "coder": coder,
        "model": model,
        "cwd": cwd,
        "priority": priority,
        "status_raw": status_raw,
        "created_at": created_at,
        "first_ts": _str_to_iso(stats.first_ts),
        "last_ts": _str_to_iso(stats.last_ts),
        "events": stats.event_count,
        "steps": stats.steps,
        "segments": stats.segments,
        "errors": stats.errors,
        "tool_counts": stats.tool_counts,
        "output_tokens": stats.output_tokens,
        "input_tokens": stats.input_tokens,
        "cache_creation_tokens": stats.cache_creation_tokens,
        "cache_read_tokens": stats.cache_read_tokens,
        "peak_context_tokens": stats.peak_context_tokens,
        "rate_limited": stats.rate_limited,
        "rate_limit_events": [e["ts"] for e in stats.rate_limit_events],
        "context_pressure": context_pressure,
        "noclose": noclose,
        "hour_hist": stats.hour_hist,
    }


def task_record_cached(tdir: Path) -> dict:
    """Return the analytics record for *tdir*.

    Relies on state.events.scan_cached for the events.jsonl mtime+size
    cache; the record itself (task.json fields + marker files) is cheap
    enough to rebuild every call.
    """
    return _build_record(tdir)


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
