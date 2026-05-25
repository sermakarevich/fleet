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


def task_runtime_stats(task_id: str) -> TaskRuntimeStats:
    """Best-effort scan of a task's directory for runtime signals."""
    tdir = task_dir(task_id)
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
