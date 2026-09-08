"""One typed analytics row per task directory.

Called by ``serve/analytics/summary.py`` (``collect_records``) and the
analytics tests. task.json bodies arrive from ``state/task_index.TaskIndex``
(the one tasks/* walker — ``collect_records`` never lists the directory
itself), single-task reads go through ``state/task_meta.TaskMeta`` (the one
task.json owner), attempt signals (noclose, context pressure) come from
``state/attempt_journal.AttemptJournal`` (the one attempts.jsonl owner),
and the events.jsonl scan comes from ``state.events`` through a
caller-owned cache.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from fleet.state.attempt_journal import AttemptJournal
from fleet.state.events import EventScanCache, scan_cached
from fleet.state.task_index import TaskIndex
from fleet.state.task_meta import TaskMeta

# Owner of cached event scans for the analytics record builder below.
_events_cache = EventScanCache()


@dataclass
class AttemptRecord:
    """One task's analytics inputs: meta + event scan + attempt signals."""

    id: str = ""
    title: str = ""
    coder: str = ""
    model: str = ""
    cwd: str = ""
    priority: int = 0
    status_raw: str = ""
    created_at: str | None = None
    first_ts: str | None = None
    last_ts: str | None = None
    events: int = 0
    steps: int = 0
    segments: int = 0
    errors: int = 0
    tool_counts: dict[str, int] = field(default_factory=dict)
    output_tokens: int = 0
    input_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    peak_context_tokens: int | None = None
    rate_limited: int = 0
    rate_limit_events: list[str] = field(default_factory=list)
    context_pressure: bool = False
    noclose: bool = False
    hour_hist: dict[str, int] = field(default_factory=dict)
    status_reconciled: str = ""
    outcome: str = "active"


def _str_to_iso(dt: datetime | None) -> str | None:
    """Render a datetime as ISO text, or None when there is none."""
    return dt.isoformat() if dt is not None else None


def _attempt_signals(task_dir: Path) -> tuple[bool, bool]:
    """Return (context_pressure, noclose) from the attempt journal.

    Context pressure is outcome-driven: any attempt that ended with
    outcome=context_pressure. Noclose means the latest attempt succeeded
    but released instead of closing (rc=0 without RESULT.json close);
    when the latest attempt has no outcome yet, the outcome-bearing tail
    of the last three attempts decides.
    """
    history = AttemptJournal.load(task_dir).rows
    pressure = any(
        entry.get("outcome") == "context_pressure" for entry in history if isinstance(entry, dict)
    )
    last = history[-1] if history else {}
    noclose = last.get("outcome") in ("success", "partial") and last.get("action") in (
        "release",
        "released",
        None,
    )
    if last.get("outcome") is None:
        noclose = any(entry.get("outcome") in ("success", "partial") for entry in history[-3:])
    return pressure, noclose


def _build_record(task_id: str, data: dict[str, Any], task_dir: Path) -> AttemptRecord:
    """Assemble one record from a raw task.json dict plus scans."""
    stats = scan_cached(task_dir, _events_cache)
    context_pressure, noclose = _attempt_signals(task_dir)
    return AttemptRecord(
        id=task_id,
        title=data.get("title", ""),
        coder=data.get("coder", ""),
        model=data.get("model", ""),
        cwd=data.get("cwd", ""),
        priority=data.get("priority", 0),
        status_raw=data.get("status", ""),
        created_at=data.get("created_at"),
        first_ts=_str_to_iso(stats.first_ts),
        last_ts=_str_to_iso(stats.last_ts),
        events=stats.event_count,
        steps=stats.steps,
        segments=stats.segments,
        errors=stats.errors,
        tool_counts=dict(stats.tool_counts),
        output_tokens=stats.output_tokens,
        input_tokens=stats.input_tokens,
        cache_creation_tokens=stats.cache_creation_tokens,
        cache_read_tokens=stats.cache_read_tokens,
        peak_context_tokens=stats.peak_context_tokens,
        rate_limited=stats.rate_limited,
        rate_limit_events=[event["ts"] for event in stats.rate_limit_events],
        context_pressure=context_pressure,
        noclose=noclose,
        hour_hist=dict(stats.hour_hist),
    )


def task_record_cached(task_dir: Path) -> AttemptRecord:
    """Return the analytics record for *task_dir*.

    Relies on state.events.scan_cached for the events.jsonl mtime+size
    cache; the record itself (task.json fields + journal signals) is cheap
    enough to rebuild every call.
    """
    meta = TaskMeta.load(task_dir)
    data = meta.to_dict() if meta is not None else {}
    return _build_record(task_dir.name, data, task_dir)


def collect_records(home: Path) -> list[AttemptRecord]:
    """Return one record per task dir under *home* that has a task.json.

    Task bodies come straight from TaskIndex.iter_meta, so the tasks
    directory is walked exactly once, by its owner.
    """
    return [
        _build_record(task_dir.name, raw, task_dir) for task_dir, raw in TaskIndex(home).iter_meta()
    ]
