from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from fleet.core.task import Task

from tests.orchestrator.test_supervisor_failures import (
    StubQueue,
    _make_supervisor,
    _task,
)


class ReconcileQueue(StubQueue):
    """StubQueue with controllable list_in_progress output."""

    def __init__(self, in_progress: list[Task], status: str = "in_progress") -> None:
        super().__init__(status=status)
        self._in_progress = in_progress

    def list_in_progress(self, limit: int = 500) -> list[Task]:
        return self._in_progress[:limit]


def test_orphan_no_run_json_released_once(tmp_path: Path) -> None:
    task = _task("t-orphan-1")
    queue = ReconcileQueue([task])
    s = _make_supervisor(tmp_path, queue)
    # No run.json written on purpose.
    s._reconcile_orphans()
    assert len(queue.released) == 1
    assert queue.released[0][0] == "t-orphan-1"
    assert "orphaned claim released" in queue.released[0][1]


def test_orphan_dead_pid_released(tmp_path: Path) -> None:
    task = _task("t-orphan-2")
    queue = ReconcileQueue([task])
    s = _make_supervisor(tmp_path, queue)
    # PID from a finished process is guaranteed dead.
    proc = subprocess.Popen(["true"])
    proc.wait()
    dead_pid = proc.pid
    task_dir = s._task_dir_for(task)
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / "run.json").write_text(
        json.dumps({"pid": dead_pid, "pgid": dead_pid}),
        encoding="utf-8",
    )
    s._reconcile_orphans()
    assert len(queue.released) == 1
    assert queue.released[0][0] == "t-orphan-2"


def test_orphan_ended_run_released_without_kill(tmp_path: Path, monkeypatch) -> None:
    task = _task("t-orphan-3")
    queue = ReconcileQueue([task])
    s = _make_supervisor(tmp_path, queue)
    task_dir = s._task_dir_for(task)
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / "run.json").write_text(
        json.dumps(
            {
                "pid": os.getpid(),
                "pgid": os.getpid(),
                "ended_at": "2026-01-01T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )

    def _fail_kill(pid, sig):
        raise AssertionError("os.kill must not be called for ended runs")

    monkeypatch.setattr(os, "kill", _fail_kill)
    s._reconcile_orphans()
    assert len(queue.released) == 1
    assert queue.released[0][0] == "t-orphan-3"
