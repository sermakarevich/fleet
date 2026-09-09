"""The one place that knows how a task directory path is built."""

from __future__ import annotations

import os
from pathlib import Path

TASK_JSON = "task.json"
RUN_JSON = "run.json"
EVENTS_JSONL = "events.jsonl"
ATTEMPTS_JSONL = "attempts.jsonl"
KILL_MARKER = ".kill"
# ADR 0004: one memory file (STATE.md), one completion contract (RESULT.json
# at the task root, present only between worker exit and reap), one
# deliverables directory (outputs/), one recorded input (prompt.md per
# attempt). Per-attempt summaries are derived on demand, never stored; the
# launch record lives in run.json["launch"]; reap snapshots instead of
# rotating.
STATE_MD = "STATE.md"
RESULT_JSON = "RESULT.json"
PROMPT_MD = "prompt.md"
OUTPUTS_DIR = "outputs"
# NOTE: the bare `.worktree` marker is gone. Isolation state lives in
# task.json as repo_root/base_ref/worktree_path (see beads/queue.py::
# set_isolation_info). Readers keep a legacy fallback for old task dirs.
# Written by workers/llm_session.py when peak context crosses the checkpoint
# threshold; read by the claude PostToolUse hook to nudge the model to wrap
# up. One-shot per attempt (the hook adds .checkpoint_sent after firing).
CHECKPOINT_REQUESTED_MARKER = ".checkpoint_requested"
CHECKPOINT_SENT_MARKER = ".checkpoint_sent"
# Touched by the claude PreCompact hook so the derived attempt summary can
# count CLI-side auto-compactions that happened inside the model session.
COMPACTED_MARKER = ".compacted"


def fleet_home() -> Path:
    """Resolve $FLEET_HOME env var or default to ~/.fleet."""
    env = os.environ.get("FLEET_HOME")
    if env:
        return Path(env).expanduser().resolve()
    return Path.home() / ".fleet"


def tasks_root(fleet_home: Path) -> Path:
    return fleet_home / "tasks"


def task_dir(fleet_home: Path, task_id: str) -> Path:
    return tasks_root(fleet_home) / task_id


def attempts_root(task_dir: Path) -> Path:
    """The `attempts/` directory that holds one subdirectory per attempt number."""
    return task_dir / "attempts"


def attempt_dir(task_dir: Path, attempt_no: int) -> Path:
    """The per-attempt directory: run.json (with launch), prompt.md,
    mcp.json, events.jsonl, log.jsonl, log.stderr, STATE.md / RESULT.json
    snapshots (taken at reap), for attempt *attempt_no*."""
    return attempts_root(task_dir) / str(attempt_no)


def state_file(task_dir: Path) -> Path:
    """The task-level worker-memory file (tasks/<id>/STATE.md)."""
    return task_dir / STATE_MD


def result_file(task_dir: Path) -> Path:
    """The task-level completion contract (tasks/<id>/RESULT.json)."""
    return task_dir / RESULT_JSON


def outputs_dir(task_dir: Path) -> Path:
    """The task-level deliverables directory (tasks/<id>/outputs/)."""
    return task_dir / OUTPUTS_DIR


def prompt_file(attempt_dir: Path) -> Path:
    """The recorded prompt for one attempt (attempts/<n>/prompt.md)."""
    return attempt_dir / PROMPT_MD
