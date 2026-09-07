"""The one place that knows how a task directory path is built."""
from __future__ import annotations

import os
from pathlib import Path

TASK_JSON = "task.json"
RUN_JSON = "run.json"
EVENTS_JSONL = "events.jsonl"
ATTEMPTS_JSONL = "attempts.jsonl"
KILL_MARKER = ".kill"
WORKTREE_MARKER = ".worktree"
CONTEXT_PRESSURE_MARKER = ".context_pressure"


def fleet_home() -> Path:
    """Resolve $FLEET_HOME env var or default to ~/.fleet."""
    env = os.environ.get("FLEET_HOME")
    if env:
        return Path(env).expanduser().resolve()
    return Path.home() / ".fleet"


def tasks_root(home: Path) -> Path:
    return home / "tasks"


def task_dir(home: Path, task_id: str) -> Path:
    return tasks_root(home) / task_id
