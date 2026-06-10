"""Shared utilities for the fleet serve layer — extracted from cli.py."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


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


# cache: tdir_str -> (events.jsonl mtime, events.jsonl size, TaskRuntimeInfo)
# (-1.0, -1) sentinel when events.jsonl is absent; safe because real mtime is large+positive.
_info_cache: dict[str, tuple[float, int, "TaskRuntimeInfo"]] = {}


def fleet_home() -> Path:
    """Resolve $FLEET_HOME env var or default to ~/.fleet."""
    env = os.environ.get("FLEET_HOME")
    if env:
        return Path(env).expanduser().resolve()
    return Path.home() / ".fleet"


def task_dir(task_id: str) -> Path:
    return fleet_home() / "tasks" / task_id


def parse_iso(ts: str) -> datetime | None:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


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


def _stats_from_dir(tdir: Path) -> TaskRuntimeStats:
    if not tdir.exists():
        return TaskRuntimeStats(
            started_at=None, last_event_at=None, events=0, context_tokens=None
        )

    started_at: datetime | None = None
    log = tdir / "log.jsonl"
    if log.exists():
        try:
            with log.open("r", encoding="utf-8") as fh:
                first_line = fh.readline().strip()
            if first_line:
                row = json.loads(first_line)
                ts = row.get("timestamp")
                if isinstance(ts, str):
                    started_at = parse_iso(ts)
        except (OSError, json.JSONDecodeError):
            pass
        if started_at is None:
            started_at = datetime.fromtimestamp(log.stat().st_mtime, tz=timezone.utc)

    events_file = tdir / "events.jsonl"
    events = 0
    last_event_at: datetime | None = None
    context_tokens: int | None = None
    if events_file.exists():
        try:
            with events_file.open("r", encoding="utf-8") as fh:
                for raw_line in fh:
                    line = raw_line.strip()
                    if not line:
                        continue
                    events += 1
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    ts_str = row.get("ts")
                    if isinstance(ts_str, str):
                        parsed = parse_iso(ts_str)
                        if parsed is not None:
                            last_event_at = parsed
                    usage = row.get("usage")
                    if isinstance(usage, dict) and row.get("kind") != "session_ended":
                        prompt = (
                            _safe_int(usage.get("input_tokens"))
                            + _safe_int(usage.get("cache_creation_input_tokens"))
                            + _safe_int(usage.get("cache_read_input_tokens"))
                        )
                        if prompt > 0:
                            context_tokens = max(context_tokens or 0, prompt)
        except OSError:
            pass

    return TaskRuntimeStats(
        started_at=started_at,
        last_event_at=last_event_at,
        events=events,
        context_tokens=context_tokens,
    )


def task_runtime_stats(task_id: str) -> TaskRuntimeStats:
    """Best-effort scan of a task's directory for runtime signals."""
    return _stats_from_dir(task_dir(task_id))


def task_runtime_stats_from_dir(tdir: Path) -> TaskRuntimeStats:
    """Same as task_runtime_stats but takes the task directory path directly."""
    return _stats_from_dir(tdir)


def _read_started_at(tdir: Path) -> datetime | None:
    log = tdir / "log.jsonl"
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
        return datetime.fromtimestamp(log.stat().st_mtime, tz=timezone.utc)
    except OSError:
        return None


def _runtime_info_from_dir(tdir: Path) -> TaskRuntimeInfo:
    """Single-pass scan: log.jsonl first line for started_at + full events.jsonl."""
    if not tdir.exists():
        return TaskRuntimeInfo(
            started_at=None, last_event_at=None, events=0, context_tokens=None,
            last_event_kind=None, last_event_detail=None,
        )

    started_at = _read_started_at(tdir)

    events_file = tdir / "events.jsonl"
    events = 0
    last_event_at: datetime | None = None
    context_tokens: int | None = None
    last_event_kind: str | None = None
    last_event_detail: str | None = None

    if events_file.exists():
        try:
            with events_file.open("r", encoding="utf-8") as fh:
                for raw_line in fh:
                    line = raw_line.strip()
                    if not line:
                        continue
                    events += 1
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    ts_str = row.get("ts")
                    if isinstance(ts_str, str):
                        parsed = parse_iso(ts_str)
                        if parsed is not None:
                            last_event_at = parsed
                    usage = row.get("usage")
                    if isinstance(usage, dict) and row.get("kind") != "session_ended":
                        prompt = (
                            _safe_int(usage.get("input_tokens"))
                            + _safe_int(usage.get("cache_creation_input_tokens"))
                            + _safe_int(usage.get("cache_read_input_tokens"))
                        )
                        if prompt > 0:
                            context_tokens = max(context_tokens or 0, prompt)
                    kind = row.get("kind")
                    if kind:
                        last_event_kind = kind
                        extra = row.get("extra") or {}
                        tool = row.get("tool_name") or extra.get("tool_name")
                        last_event_detail = str(tool) if tool else None
        except OSError:
            pass

    return TaskRuntimeInfo(
        started_at=started_at,
        last_event_at=last_event_at,
        events=events,
        context_tokens=context_tokens,
        last_event_kind=last_event_kind,
        last_event_detail=last_event_detail,
    )


def task_runtime_info_cached(tdir: Path) -> TaskRuntimeInfo:
    """Return TaskRuntimeInfo for tdir; re-reads only when events.jsonl mtime/size changes."""
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

    result = _runtime_info_from_dir(tdir)
    _info_cache[cache_key] = (file_mtime, file_size, result)
    return result


def task_files_touched_from_dir(tdir: Path) -> int:
    """Count unique files touched (read/edited/written) across a task's events."""
    events_file = tdir / "events.jsonl"
    if not events_file.exists():
        return 0
    _touch_tools = frozenset({"Read", "Edit", "Write", "NotebookEdit"})
    files: set[str] = set()
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
                if row.get("kind") != "tool_use":
                    continue
                if (row.get("tool_name") or "") not in _touch_tools:
                    continue
                raw_data = row.get("raw") or {}
                inp = raw_data.get("input") or {}
                fpath = inp.get("file_path") or inp.get("path")
                if fpath:
                    files.add(str(fpath))
    except OSError:
        pass
    return len(files)
