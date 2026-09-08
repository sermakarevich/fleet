"""Shared helper for building a fake task directory in tests.

Several test modules (state/, workers/, orchestrator/) need a task directory
with one or more attempt subdirectories, an `attempts.jsonl` history, and
artifacts. This module is the one place that builds that fixture so each
test file doesn't reinvent its own ad-hoc version.
"""

from __future__ import annotations

import json
from pathlib import Path

_DEFAULT_STARTED = "2026-01-01T00:00:00+00:00"
_DEFAULT_ENDED = "2026-01-01T00:05:00+00:00"


def make_task_dir(tmp_path: Path, task_id: str = "t-001") -> Path:
    """Create `tmp_path/tasks/<task_id>/artifacts/` and return the task dir."""
    task_dir = tmp_path / "tasks" / task_id
    (task_dir / "artifacts").mkdir(parents=True, exist_ok=True)
    return task_dir


def make_attempt(
    task_dir: Path,
    n: int,
    *,
    coder: str | None = "claude",
    model: str | None = "sonnet",
    worker: str | None = "task.fresh",
    outcome: str | None = None,
    reason: str | None = None,
    exit_code: int | None = None,
    action: str | None = None,
    started_at: str | None = _DEFAULT_STARTED,
    ended_at: str | None = None,
) -> Path:
    """Append a start (and optional end) line to attempts.jsonl for attempt *n*.

    Creates and returns `task_dir/attempts/<n>/`. Pass *outcome* (or
    *ended_at*) to also record the "end" line, as if the attempt finished.
    """
    task_dir.mkdir(parents=True, exist_ok=True)
    attempts_path = task_dir / "attempts.jsonl"
    start = {
        "event": "start",
        "n": n,
        "ts": started_at,
        "coder": coder,
        "model": model,
        "worker": worker,
    }
    with attempts_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(start) + "\n")

    if outcome is not None or ended_at is not None:
        end = {
            "event": "end",
            "n": n,
            "ts": ended_at or _DEFAULT_ENDED,
            "outcome": outcome,
            "exit_code": exit_code,
            "reason": reason,
            "action": action,
        }
        with attempts_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(end) + "\n")

    attempt_dir = task_dir / "attempts" / str(n)
    attempt_dir.mkdir(parents=True, exist_ok=True)
    return attempt_dir
