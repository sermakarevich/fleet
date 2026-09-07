"""The one events.jsonl reader, plus the derived stats every caller needs.

``iter_events`` is the single tolerant line-by-line reader. ``scan``/
``scan_cached`` compute everything downstream code has historically
recomputed by hand: counts, timestamps, token totals, per-file touch
counts, tool usage, and rate-limit events.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

_TOUCH_TOOLS = {"Read": "read", "Edit": "edit", "Write": "write", "NotebookEdit": "edit"}


def parse_iso(ts: str) -> datetime | None:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def safe_int(v: object) -> int:
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


def iter_events(task_dir: Path) -> Iterator[dict]:
    """Yield each parsed JSON object from task_dir/events.jsonl.

    Blank and malformed lines are skipped silently.
    """
    events_file = task_dir / "events.jsonl"
    if not events_file.exists():
        return
    try:
        with events_file.open("r", encoding="utf-8") as fh:
            for raw_line in fh:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(row, dict):
                    yield row
    except OSError:
        return


@dataclass
class FileCounts:
    read: int = 0
    edit: int = 0
    write: int = 0


@dataclass
class EventStats:
    event_count: int = 0
    first_ts: datetime | None = None
    last_ts: datetime | None = None
    last_kind: str | None = None
    last_detail: str | None = None
    peak_context_tokens: int | None = None
    current_context_tokens: int | None = None
    steps: int = 0
    segments: int = 0
    errors: int = 0
    tool_counts: dict[str, int] = field(default_factory=dict)
    output_tokens: int = 0
    input_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    files_touched: dict[str, FileCounts] = field(default_factory=dict)
    hour_hist: dict[str, int] = field(default_factory=dict)
    context_pressure: bool = False
    rate_limited: int = 0
    rate_limit_events: list[dict] = field(default_factory=list)

    @property
    def files_touched_count(self) -> int:
        return len(self.files_touched)


def scan(task_dir: Path) -> EventStats:
    """Single-pass scan of task_dir/events.jsonl into an EventStats."""
    stats = EventStats()
    tool_result_counts: dict[str, int] = {}
    tool_use_counts: dict[str, int] = {}
    segments_set: set[str] = set()

    for row in iter_events(task_dir):
        stats.event_count += 1

        ts_str = row.get("ts")
        ts_dt: datetime | None = None
        if isinstance(ts_str, str):
            ts_dt = parse_iso(ts_str)
        if ts_dt is not None:
            if stats.first_ts is None or ts_dt < stats.first_ts:
                stats.first_ts = ts_dt
            if stats.last_ts is None or ts_dt > stats.last_ts:
                stats.last_ts = ts_dt
            key = f"{ts_dt.weekday()}-{ts_dt.hour}"
            stats.hour_hist[key] = stats.hour_hist.get(key, 0) + 1

        kind = row.get("kind")
        if kind:
            stats.last_kind = kind
            extra = row.get("extra") or {}
            tool = row.get("tool_name") or extra.get("tool_name")
            stats.last_detail = str(tool) if tool else None

        if kind == "session_started":
            stats.steps += 1

        sid = row.get("session_id")
        if sid is not None:
            segments_set.add(sid)

        if kind == "error":
            stats.errors += 1

        if kind == "tool_result":
            tn = row.get("tool_name")
            if tn is not None:
                tool_result_counts[tn] = tool_result_counts.get(tn, 0) + 1
        elif kind == "tool_use":
            tn = row.get("tool_name")
            if tn is not None:
                tool_use_counts[tn] = tool_use_counts.get(tn, 0) + 1

        if kind == "tool_use":
            tool_name = row.get("tool_name") or ""
            op = _TOUCH_TOOLS.get(tool_name)
            if op:
                raw_data = row.get("raw") or {}
                inp = raw_data.get("input") or {}
                fpath = inp.get("file_path") or inp.get("path")
                if fpath:
                    fpath = str(fpath)
                    counts = stats.files_touched.setdefault(fpath, FileCounts())
                    setattr(counts, op, getattr(counts, op) + 1)

        if kind != "session_ended":
            usage = row.get("usage")
            if isinstance(usage, dict):
                stats.output_tokens += safe_int(usage.get("output_tokens"))
                stats.input_tokens += safe_int(usage.get("input_tokens"))
                stats.cache_creation_tokens += safe_int(
                    usage.get("cache_creation_input_tokens")
                )
                stats.cache_read_tokens += safe_int(
                    usage.get("cache_read_input_tokens")
                )
                ctx = (
                    safe_int(usage.get("input_tokens"))
                    + safe_int(usage.get("cache_creation_input_tokens"))
                    + safe_int(usage.get("cache_read_input_tokens"))
                )
                if ctx > 0:
                    stats.current_context_tokens = ctx
                    stats.peak_context_tokens = (
                        ctx
                        if stats.peak_context_tokens is None
                        else max(stats.peak_context_tokens, ctx)
                    )

        rate_info = row.get("rate_info")
        if kind in ("rate_limit", "rate_limit_info") and isinstance(rate_info, dict):
            if rate_info.get("status") == "rejected":
                stats.rate_limited += 1
                resets_at = rate_info.get("resets_at")
                duration_sec: float | None = None
                if resets_at is not None and ts_dt is not None:
                    try:
                        duration_sec = float(resets_at) - ts_dt.timestamp()
                    except (TypeError, ValueError):
                        duration_sec = None
                stats.rate_limit_events.append(
                    {
                        "ts": ts_str,
                        "provider": rate_info.get("provider") or "unknown",
                        "duration_sec": duration_sec,
                    }
                )

        if kind == "context_pressure":
            stats.context_pressure = True

    stats.segments = len(segments_set)
    stats.tool_counts = tool_result_counts if tool_result_counts else tool_use_counts
    return stats


# cache: tdir_str -> (events.jsonl mtime, events.jsonl size, EventStats)
# (-1.0, -1) sentinel when events.jsonl is absent; safe because real mtime is large+positive.
_cache: dict[str, tuple[float, int, EventStats]] = {}


def scan_cached(task_dir: Path) -> EventStats:
    """Same as scan(), re-scanning only when events.jsonl mtime/size changed."""
    events_file = task_dir / "events.jsonl"
    cache_key = str(task_dir)

    try:
        st = events_file.stat()
        file_mtime: float = st.st_mtime
        file_size: int = st.st_size
    except OSError:
        file_mtime, file_size = -1.0, -1

    entry = _cache.get(cache_key)
    if entry is not None and entry[0] == file_mtime and entry[1] == file_size:
        return entry[2]

    result = scan(task_dir)
    _cache[cache_key] = (file_mtime, file_size, result)
    return result
