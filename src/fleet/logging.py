from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import IO

import structlog

from fleet.schemas import Event
from fleet.redact import redact

_JSON_PROCESSORS: list = [
    structlog.contextvars.merge_contextvars,
    structlog.processors.TimeStamper(fmt="iso"),
    structlog.stdlib.add_log_level,
    structlog.processors.JSONRenderer(),
]


class _DualSink:
    """Final processor: writes JSON to a file and console-style to a stream."""

    def __init__(self, json_file: IO[str], console_file: IO[str]) -> None:
        self._json_file = json_file
        self._console_file = console_file
        self._json_renderer = structlog.processors.JSONRenderer()
        colors = bool(getattr(console_file, "isatty", lambda: False)())
        self._console_renderer = structlog.dev.ConsoleRenderer(colors=colors)
        self._console_ts = structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%S")

    def __call__(self, logger, method_name, event_dict):
        json_line = self._json_renderer(logger, method_name, dict(event_dict))
        console_ed = dict(event_dict)
        console_ed.pop("timestamp", None)
        console_ed = self._console_ts(logger, method_name, console_ed)
        console_line = self._console_renderer(logger, method_name, console_ed)
        self._json_file.write(json_line + "\n")
        self._json_file.flush()
        self._console_file.write(console_line + "\n")
        self._console_file.flush()
        return ""


class _NullLogger:
    """No-op logger; all writing is done by _DualSink."""

    def msg(self, _):
        return None

    log = msg
    info = msg
    error = msg
    debug = msg
    warning = msg
    critical = msg
    failure = msg
    exception = msg


class TaskLog:
    def __init__(
        self,
        log: structlog.BoundLogger,
        stderr_file: IO[bytes],
        _jsonl_file: IO[str],
    ) -> None:
        self.log = log
        self.stderr_file = stderr_file
        self._jsonl_file = _jsonl_file

    def __enter__(self) -> TaskLog:
        return self

    def __exit__(self, *_) -> None:
        self._jsonl_file.flush()
        self._jsonl_file.close()
        self.stderr_file.flush()
        self.stderr_file.close()


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
        _DualSink(fleet_file, sys.stderr),
    ]
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.BoundLogger,
        context_class=dict,
        logger_factory=lambda *args, **kwargs: _NullLogger(),
    )
    return structlog.get_logger().bind(component="supervisor", pid=os.getpid())


def open_task_log(task_dir: Path, task_id: str) -> TaskLog:
    """Open the per-task JSONL and stderr files (append mode) at the task dir root."""
    task_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = task_dir / "log.jsonl"
    stderr_path = task_dir / "log.stderr"
    jsonl_file = jsonl_path.open("a", encoding="utf-8")
    stderr_file = stderr_path.open("ab", buffering=0)
    log = structlog.wrap_logger(
        structlog.PrintLogger(jsonl_file),
        processors=_JSON_PROCESSORS,
    ).bind(task_id=task_id, pid=os.getpid())
    return TaskLog(
        log=log,
        stderr_file=stderr_file,
        _jsonl_file=jsonl_file,
    )


def append_event(task_dir: Path, evt: Event) -> None:
    """Append one normalized Event line to <task_dir>/events.jsonl.

    Never truncates prior content (append mode, line-flushed).
    Redacts credentials before serialising.
    """
    payload: dict = {
        "kind": evt.kind,
        "ts": evt.ts.isoformat(),
        "session_id": evt.session_id,
        "tool_name": evt.tool_name,
        "usage": evt.usage,
        "rate_info": evt.rate_info,
        "raw": evt.raw,
    }
    payload = redact(payload)
    task_dir.mkdir(parents=True, exist_ok=True)
    events_path = task_dir / "events.jsonl"
    with events_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload) + "\n")
        f.flush()
