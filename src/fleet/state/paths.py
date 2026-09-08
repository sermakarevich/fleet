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
# Written by workers/llm_session.py when peak context crosses the checkpoint
# threshold; read by the claude PostToolUse hook to nudge the model to wrap
# up. One-shot per attempt (the hook adds .checkpoint_sent after firing).
CHECKPOINT_REQUESTED_MARKER = ".checkpoint_requested"
CHECKPOINT_SENT_MARKER = ".checkpoint_sent"
# Touched by the claude PreCompact hook so SUMMARY.md can count CLI-side
# auto-compactions that happened inside the model session.
COMPACTED_MARKER = ".compacted"


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


def attempts_root(task_dir: Path) -> Path:
    """The `attempts/` directory that holds one subdirectory per attempt number."""
    return task_dir / "attempts"


def attempt_dir_path(task_dir: Path, n: int) -> Path:
    """The per-attempt directory: run.json, events.jsonl, log.jsonl, log.stderr,
    RESULT.json, HANDOFF.md, SUMMARY.md, launch.json for attempt *n*."""
    return attempts_root(task_dir) / str(n)
