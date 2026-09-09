from __future__ import annotations

import contextlib
import json
import os
import sys
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import IO

import structlog

from fleet.core.redact import redact
from fleet.core.task import Event, EventKind

EVENTS_MAX_BYTES: int = 50 * 1024 * 1024
EVENTS_KEEP_ROTATED: int = 1


def _rotate_if_needed(events_path: Path) -> None:
    try:
        if events_path.stat().st_size < EVENTS_MAX_BYTES:
            return
    except FileNotFoundError:
        return
    # Shift .N -> .N+1, drop the oldest beyond EVENTS_KEEP_ROTATED
    for n in range(EVENTS_KEEP_ROTATED, 0, -1):
        src = events_path.with_name(f"{events_path.name}.{n}")
        if not src.exists():
            continue
        if n == EVENTS_KEEP_ROTATED:
            src.unlink()
        else:
            src.replace(events_path.with_name(f"{events_path.name}.{n + 1}"))
    events_path.replace(events_path.with_name(f"{events_path.name}.1"))


_JSON_PROCESSORS: list = [
    structlog.contextvars.merge_contextvars,
    structlog.processors.TimeStamper(fmt="iso"),
    structlog.stdlib.add_log_level,
    structlog.processors.JSONRenderer(),
]


def make_dual_sink(json_file: IO[str], console_file: IO[str]) -> Callable:
    """Build the final structlog processor writing JSON to a file, console to a stream."""
    json_renderer = structlog.processors.JSONRenderer()
    colors = bool(getattr(console_file, "isatty", lambda: False)())
    console_renderer = structlog.dev.ConsoleRenderer(colors=colors)
    console_ts = structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%S")

    def dual_sink(logger, method_name, event_dict):
        # structlog processors are untyped; bead 2 owns journal.
        json_line = json_renderer(logger, method_name, dict(event_dict))
        console_ed = dict(event_dict)
        console_ed.pop("timestamp", None)
        console_ed = console_ts(logger, method_name, console_ed)  # type: ignore[assignment]
        console_line = console_renderer(logger, method_name, console_ed)
        # JSONRenderer returns str with default settings.
        json_file.write(json_line + "\n")  # type: ignore[arg-type, operator]
        json_file.flush()
        # ConsoleRenderer returns str when colors=False.
        console_file.write(console_line + "\n")
        console_file.flush()
        return ""

    return dual_sink


class _NullLogger:
    """No-op logger; all writing is done by the dual sink."""

    def __getattr__(self, _name: str) -> Callable[..., None]:
        return lambda *args, **kwargs: None


@dataclass(frozen=True)
class TaskLogRecord:
    """Handles for one attempt's logs: JSONL logger plus the raw stderr file."""

    log: structlog.BoundLogger
    stderr_file: IO[bytes]


def setup_supervisor_logger(log_root: Path) -> structlog.BoundLogger:
    """Configure structlog globally and return a supervisor BoundLogger.

    Writes JSON to <log_root>/fleet-<date>.jsonl (append) and renders
    human-readable console output to stderr.
    """
    log_root.mkdir(parents=True, exist_ok=True)
    date = datetime.now().strftime("%Y-%m-%d")
    fleet_path = log_root / f"fleet-{date}.jsonl"
    fleet_file = fleet_path.open("a", encoding="utf-8")
    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.stdlib.add_log_level,
        make_dual_sink(fleet_file, sys.stderr),
    ]
    structlog.configure(
        processors=processors,  # type: ignore[arg-type]  # dual sink is untyped; bead 2 owns journal
        wrapper_class=structlog.BoundLogger,
        context_class=dict,
        logger_factory=lambda *args, **kwargs: _NullLogger(),
    )
    return structlog.get_logger().bind(component="supervisor", pid=os.getpid())


@contextlib.contextmanager
def open_task_log(attempt_dir: Path, task_id: str) -> Iterator[TaskLogRecord]:
    """Open this attempt's log.jsonl and log.stderr files (append mode).

    *attempt_dir* is the per-attempt directory (`tasks/<id>/attempts/<n>`),
    not the task directory root. Yields a frozen record; both files are
    flushed and closed on exit.
    """
    attempt_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = attempt_dir / "log.jsonl"
    stderr_path = attempt_dir / "log.stderr"
    jsonl_file = jsonl_path.open("a", encoding="utf-8")
    stderr_file = stderr_path.open("ab", buffering=0)
    log = structlog.wrap_logger(
        structlog.PrintLogger(jsonl_file),
        processors=_JSON_PROCESSORS,
    ).bind(task_id=task_id, pid=os.getpid())
    try:
        yield TaskLogRecord(log=log, stderr_file=stderr_file)
    finally:
        jsonl_file.flush()
        jsonl_file.close()
        stderr_file.flush()
        stderr_file.close()


def append_event(attempt_dir: Path, event: Event) -> None:
    """Append one normalized Event line to <attempt_dir>/events.jsonl.

    *attempt_dir* is the per-attempt directory. Never truncates prior
    content (append mode, line-flushed). Redacts credentials before
    serialising.
    """
    payload: dict = {
        "kind": event.kind.value if isinstance(event.kind, EventKind) else event.kind,
        "ts": event.ts.isoformat(),
        "session_id": event.session_id,
        "tool_name": event.tool_name,
        "usage": event.usage,
        "rate_info": event.rate_info,
        "raw": event.raw,
    }
    payload = redact(payload)
    attempt_dir.mkdir(parents=True, exist_ok=True)
    events_path = attempt_dir / "events.jsonl"
    with contextlib.suppress(OSError):
        _rotate_if_needed(events_path)
    with events_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload) + "\n")
        f.flush()
