"""Task runtime stats: log.jsonl started_at plus state.events scan results.

State-layer helper (it reads task directories). Called by
``state/task_summary.py`` (the shared summary dict), ``cli/tasks.py``
(`fleet tail` header), ``serve/watcher.py`` (session_ended enrichment),
and previously by ``orchestrator/status_log.py``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from fleet.state.attempts import latest_attempt_dir
from fleet.state.events import EventScanCache, event_stats_cached, parse_iso
from fleet.state.paths import fleet_home, task_dir

# Owner of cached event scans for the state stats helpers below.
_events_cache = EventScanCache()


@dataclass
class TaskRuntimeStats:
    """Per-task runtime signals: start time, last event, counts, context peak."""

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


def _read_started_at(task_dir: Path) -> datetime | None:
    attempt_dir = latest_attempt_dir(task_dir)
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


def task_runtime_info(task_dir: Path) -> TaskRuntimeInfo:
    """Return TaskRuntimeInfo for task_dir; re-scans events.jsonl only on change."""
    stats = event_stats_cached(task_dir, _events_cache)
    return TaskRuntimeInfo(
        started_at=_read_started_at(task_dir),
        last_event_at=stats.last_ts,
        events=stats.event_count,
        context_tokens=stats.peak_context_tokens,
        last_event_kind=stats.last_kind,
        last_event_detail=stats.last_detail,
    )


def task_runtime_stats(task_dir: Path) -> TaskRuntimeStats:
    """Same fields as TaskRuntimeInfo, minus the last-event-kind/detail pair."""
    stats = event_stats_cached(task_dir, _events_cache)
    return TaskRuntimeStats(
        started_at=_read_started_at(task_dir),
        last_event_at=stats.last_ts,
        events=stats.event_count,
        context_tokens=stats.peak_context_tokens,
    )


def task_runtime_stats_for(task_id: str) -> TaskRuntimeStats:
    """Best-effort scan of a task's directory for runtime signals."""
    return task_runtime_stats(task_dir(fleet_home(), task_id))


def task_files_touched(task_dir: Path) -> int:
    """Count unique files touched (read/edited/written) across a task's events."""
    return event_stats_cached(task_dir, _events_cache).files_touched_count
