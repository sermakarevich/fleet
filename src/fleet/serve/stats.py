"""Task runtime stats: log.jsonl started_at + state.events scan results."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from fleet.state.attempts import latest_attempt_dir
from fleet.state.events import EventScanCache, parse_iso, scan_cached
from fleet.state.paths import fleet_home
from fleet.state.paths import task_dir as _task_dir

# Owner of cached event scans for the serve stats helpers below.
_events_cache = EventScanCache()


@dataclass
class TaskRuntimeStats:
    started_at: datetime | None
    last_event_at: datetime | None
    events: int
    context_tokens: int | None  # peak (input + cache_creation + cache_read) tokens


@dataclass
class TaskRuntimeInfo:
    """Combined single-pass result: stats + last-event fields."""
    started_at: datetime | None
    last_event_at: datetime | None
    events: int
    context_tokens: int | None
    last_event_kind: str | None
    last_event_detail: str | None


def _read_started_at(tdir: Path) -> datetime | None:
    attempt_dir = latest_attempt_dir(tdir)
    if attempt_dir is None:
        return None
    log = attempt_dir / "log.jsonl"
    if not log.exists():
        return None
    try:
        with log.open("r", encoding="utf-8") as fh:
            first_line = fh.readline().strip()
        if first_line:
            row = json.loads(first_line)
            ts = row.get("timestamp")
            if isinstance(ts, str):
                parsed = parse_iso(ts)
                if parsed is not None:
                    return parsed
    except (OSError, json.JSONDecodeError):
        pass
    try:
        return datetime.fromtimestamp(log.stat().st_mtime, tz=UTC)
    except OSError:
        return None


def task_runtime_info_cached(tdir: Path) -> TaskRuntimeInfo:
    """Return TaskRuntimeInfo for tdir; re-scans events.jsonl only on change."""
    stats = scan_cached(tdir, _events_cache)
    return TaskRuntimeInfo(
        started_at=_read_started_at(tdir),
        last_event_at=stats.last_ts,
        events=stats.event_count,
        context_tokens=stats.peak_context_tokens,
        last_event_kind=stats.last_kind,
        last_event_detail=stats.last_detail,
    )


def task_runtime_stats_from_dir(tdir: Path) -> TaskRuntimeStats:
    """Same fields as TaskRuntimeInfo, minus the last-event-kind/detail pair."""
    stats = scan_cached(tdir, _events_cache)
    return TaskRuntimeStats(
        started_at=_read_started_at(tdir),
        last_event_at=stats.last_ts,
        events=stats.event_count,
        context_tokens=stats.peak_context_tokens,
    )


def task_runtime_stats(task_id: str) -> TaskRuntimeStats:
    """Best-effort scan of a task's directory for runtime signals."""
    return task_runtime_stats_from_dir(_task_dir(fleet_home(), task_id))


def task_files_touched_from_dir(tdir: Path) -> int:
    """Count unique files touched (read/edited/written) across a task's events."""
    return scan_cached(tdir, _events_cache).files_touched_count
