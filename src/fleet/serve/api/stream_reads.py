"""Thread helpers for the task stream routes (logs, files, events).

Called by serve/api/tasks_stream.py via `asyncio.to_thread` (the
blocking-I/O rule in serve/api/__init__.py): handlers never read the
filesystem on the event-loop thread. Every helper here is sync.
"""

from __future__ import annotations

from pathlib import Path

from fleet.serve.api.artifact_files import read_text_or_empty
from fleet.serve.api.task_summary import event_to_json, parse_log_line
from fleet.state.events import EventScanCache, event_stats_cached, iter_events

_events_cache = EventScanCache()


def read_log_entries(log_file: Path, level: str | None) -> list[dict]:
    """Parsed log.jsonl rows, optionally filtered by level."""
    entries: list[dict] = []
    for raw in read_text_or_empty(log_file).splitlines():
        entry = parse_log_line(raw)
        if entry is None or (level and entry.level != level):
            continue
        entries.append(
            {
                "ts": entry.ts,
                "level": entry.level,
                "message": entry.message,
                "extra": entry.extra,
            }
        )
    return entries


def files_payload(task_path: Path) -> list[dict]:
    """Per-file read/edit/write counts from the event scan."""
    counts = event_stats_cached(task_path, _events_cache).files_touched
    return [
        {"path": path, "read": fc.read, "edit": fc.edit, "write": fc.write}
        for path, fc in sorted(counts.items())
    ]


def events_page(
    task_dir: Path, offset: int | None, limit: int, allow_kinds: set[str] | None
) -> dict:
    """Whole-task event history page across attempts."""
    rows = [
        row
        for row in iter_events(task_dir)
        if allow_kinds is None or row.get("kind", "") in allow_kinds
    ]
    total = len(rows)
    start = max(0, total - limit) if offset is None else max(0, offset)
    page = [event_to_json(row, start + i) for i, row in enumerate(rows[start : start + limit])]
    return {"total": total, "offset": start, "events": page}
