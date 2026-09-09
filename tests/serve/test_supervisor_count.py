"""Tests for the supervisor live-active count (unit under test: serve/api/supervisor.py)."""

from __future__ import annotations

import json
import os
from pathlib import Path

from fleet.serve.api.supervisor import _count_active

_START_LINE = {
    "event": "start",
    "n": 1,
    "ts": "2026-01-01T00:00:00+00:00",
    "coder": "claude",
    "model": "sonnet",
    "worker": "task",
}


def _make_task(fleet_home: Path, task_id: str, *, status: str, run: dict | None) -> None:
    """One task dir with task.json, a start line and an optional run.json."""
    task_dir = fleet_home / "tasks" / task_id
    attempt_dir = task_dir / "attempts" / "1"
    attempt_dir.mkdir(parents=True)
    (task_dir / "task.json").write_text(
        json.dumps({"id": task_id, "title": task_id, "status": status})
    )
    (task_dir / "attempts.jsonl").write_text(json.dumps(_START_LINE) + "\n")
    if run is not None:
        (attempt_dir / "run.json").write_text(json.dumps(run))


def test_count_active_skips_ended_and_stale(tmp_path: Path) -> None:
    """One live + one ended + one stale in_progress task counts as 1 (ADR 0009)."""
    _make_task(tmp_path, "live", status="in_progress", run={"pid": os.getpid()})
    _make_task(
        tmp_path,
        "ended",
        status="in_progress",
        run={"pid": os.getpid(), "ended_at": "2026-01-02T00:00:00+00:00"},
    )
    _make_task(tmp_path, "stale", status="in_progress", run={"pid": 999999999})
    _make_task(tmp_path, "done", status="done", run={"pid": os.getpid()})

    assert _count_active(tmp_path) == 1
