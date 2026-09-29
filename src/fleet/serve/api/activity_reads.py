"""Merged activity feed reads for GET /api/tasks/{id}/activity (ADR 0017 U1).

Called by serve/api/tasks_activity.py via `asyncio.to_thread` (the
blocking-I/O rule in serve/api/__init__.py): handlers never read the
filesystem on the event-loop thread. Every helper here is sync.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fleet.serve.api.task_summary import event_to_json, parse_log_line
from fleet.state.attempts import latest_attempt_dir
from fleet.state.events import attempt_dirs_sorted

#: Lowest fleet-log level kept per min_level value (events always pass).
_LEVEL_ORDER = {"debug": 0, "info": 1, "warning": 2, "error": 3}

#: Unknown log levels filter as info (visible unless min_level is warning+).
_DEFAULT_LEVEL_RANK = 1

#: Truncation for the latest attempt's stderr tail.
STDERR_TAIL_LINES = 40

#: Feed cache budget: at most this many (task_dir, min_level) entries.
_MAX_CACHE_ENTRIES = 32

#: (task_dir, min_level) -> (fingerprint, feed). Fingerprint is one
#: (path, mtime_ns, size) triple per events.jsonl/log.jsonl read, so an
#: appended line (or a new attempt) rebuilds the feed on the next poll.
_feed_cache: dict[tuple[str, str], tuple[tuple[Any, ...], list[dict]]] = {}


def _file_stamp(path: Path) -> tuple[str, int, int]:
    """Cache stamp for one feed file; (-1, -1) when missing/unreadable."""
    try:
        st = path.stat()
    except OSError:
        return (str(path), -1, -1)
    return (str(path), st.st_mtime_ns, st.st_size)


def _fingerprint(task_dir: Path) -> tuple[Any, ...]:
    """Stamp of every events.jsonl/log.jsonl under every attempt dir."""
    stamps: list[tuple[str, int, int]] = []
    for attempt in attempt_dirs_sorted(task_dir):
        stamps.append(_file_stamp(attempt / "events.jsonl"))
        stamps.append(_file_stamp(attempt / "log.jsonl"))
    return tuple(stamps)


def _log_rows(attempt_path: Path, threshold: int) -> list[tuple[str, int, dict]]:
    """(ts, order, payload) for one attempt's log.jsonl above *threshold*."""
    rows: list[tuple[str, int, dict]] = []
    try:
        text = (attempt_path / "log.jsonl").read_text(encoding="utf-8")
    except OSError:
        return rows
    for line in text.splitlines():
        entry = parse_log_line(line)
        if entry is None:
            continue
        if _LEVEL_ORDER.get(entry.level.lower(), _DEFAULT_LEVEL_RANK) < threshold:
            continue
        rows.append(
            (
                entry.ts,
                1,
                {
                    "ts": entry.ts,
                    "kind": entry.level,
                    "summary": entry.message,
                    "raw": entry.extra,
                },
            )
        )
    return rows


def _event_rows(attempt_path: Path) -> list[tuple[str, int, dict]]:
    """(ts, order, payload) for one attempt's events.jsonl (0 sorts first)."""
    rows: list[tuple[str, int, dict]] = []
    try:
        text = (attempt_path / "events.jsonl").read_text(encoding="utf-8")
    except OSError:
        return rows
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            ts = row.get("ts")
            rows.append((ts if isinstance(ts, str) else "", 0, row))
    return rows


def _read_feed(task_dir: Path, min_level: str) -> list[dict]:
    """Full merged feed for every attempt, seq assigned in order."""
    threshold = _LEVEL_ORDER.get(min_level.lower(), _LEVEL_ORDER["warning"])
    shaped: list[dict] = []
    for attempt_path in attempt_dirs_sorted(task_dir):
        try:
            attempt = int(attempt_path.name)
        except ValueError:
            continue
        rows = _event_rows(attempt_path) + _log_rows(attempt_path, threshold)
        # Stable sort: ISO-8601 strings compare chronologically; events
        # before logs on equal ts; empty ts keeps file order within its group.
        rows.sort(key=lambda item: (item[0], item[1]))
        for _, order, payload in rows:
            if order == 0:
                item = event_to_json(payload)
                item.pop("i", None)
                item["source"] = "event"
            else:
                item = {
                    "ts": payload["ts"],
                    "kind": payload["kind"],
                    "tool_name": None,
                    "usage": None,
                    "summary": payload["summary"],
                    "raw": payload["raw"],
                    "source": "log",
                }
            item["attempt"] = attempt
            shaped.append(item)
    for seq, item in enumerate(shaped):
        item["seq"] = seq
    return shaped


def build_feed(task_dir: Path, min_level: str = "warning") -> list[dict]:
    """Merged event+log feed across attempts, cached by file fingerprint."""
    key = (str(task_dir), min_level)
    fingerprint = _fingerprint(task_dir)
    entry = _feed_cache.get(key)
    if entry is not None and entry[0] == fingerprint:
        return entry[1]
    feed = _read_feed(task_dir, min_level)
    _feed_cache[key] = (fingerprint, feed)
    while len(_feed_cache) > _MAX_CACHE_ENTRIES:
        _feed_cache.pop(next(iter(_feed_cache)))
    return feed


def latest_attempt_no(task_dir: Path) -> int:
    """Highest attempt number with a directory, 0 when there are none."""
    dirs = attempt_dirs_sorted(task_dir)
    if not dirs:
        return 0
    try:
        return int(dirs[-1].name)
    except ValueError:
        return 0


def stderr_tail(task_dir: Path, lines: int = STDERR_TAIL_LINES) -> dict | None:
    """Last *lines* of the latest attempt's log.stderr, None when absent."""
    attempt_path = latest_attempt_dir(task_dir)
    if attempt_path is None or not attempt_path.is_dir():
        dirs = attempt_dirs_sorted(task_dir)
        attempt_path = dirs[-1] if dirs else None
    if attempt_path is None:
        return None
    try:
        text = (attempt_path / "log.stderr").read_text(encoding="utf-8")
    except OSError:
        return None
    tail = [line.rstrip("\n") for line in text.splitlines()[-lines:]]
    if not tail:
        return None
    try:
        attempt = int(attempt_path.name)
    except ValueError:
        attempt = 0
    return {"attempt": attempt, "lines": tail}


def activity_payload(task_dir: Path, min_level: str = "warning") -> dict:
    """Full activity payload: feed items, total, latest attempt, stderr."""
    feed = build_feed(task_dir, min_level)
    return {
        "items": feed,
        "total": len(feed),
        "latest_attempt": latest_attempt_no(task_dir),
        "stderr": stderr_tail(task_dir),
    }
