"""Startup reconciliation contract (was: orphan release; now: lease reclaim).

`Supervisor.run` calls `reconcile_leases()` at startup. Unlike the old
orphan sweep, a bead with no attempt dir / no run.json / no heartbeat
keys is NEVER touched (human-claimed beads), and a stale lease reclaims
only on a provably dead pid. Full case coverage lives in
test_leases.py; these tests pin the startup-path guarantees that
changed.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from tests.helpers.task_dir import make_attempt
from tests.orchestrator.test_leases import LeaseQueue
from tests.orchestrator.test_supervisor_failures import (
    _make_supervisor,
    _task,
)


def _dead_pid() -> int:
    proc = subprocess.Popen(["true"])
    proc.wait()
    return proc.pid


def test_startup_reconcile_leaves_bead_without_attempt_dir(tmp_path: Path) -> None:
    """Human-claimed bead (no task dir): the old sweep released it; now untouched."""
    task = _task("t-orphan-1")
    queue = LeaseQueue([task])
    s = _make_supervisor(tmp_path, queue)
    # No task dir written on purpose.
    s.reconcile_leases()
    assert queue.released == []


def test_startup_reconcile_leaves_run_without_heartbeat(tmp_path: Path) -> None:
    """Dead pid but old-format run.json (no lease keys): proves nothing, untouched."""
    task = _task("t-orphan-2")
    queue = LeaseQueue([task])
    s = _make_supervisor(tmp_path, queue)
    task_dir = s._task_dir_for(task)
    attempt_dir = make_attempt(task_dir, 1)
    (attempt_dir / "run.json").write_text(
        json.dumps({"pid": _dead_pid(), "pgid": _dead_pid()}),
        encoding="utf-8",
    )
    s.reconcile_leases()
    assert queue.released == []


def test_startup_reconcile_leaves_ended_attempt(tmp_path: Path) -> None:
    """Ended run.json + journaled end line: reap owns the bead, no double-release."""
    task = _task("t-orphan-3")
    queue = LeaseQueue([task])
    s = _make_supervisor(tmp_path, queue)
    task_dir = s._task_dir_for(task)
    attempt_dir = make_attempt(
        task_dir, 1, outcome="failure", reason="rc=1", exit_code=1, action="release"
    )
    (attempt_dir / "run.json").write_text(
        json.dumps(
            {
                "pid": _dead_pid(),
                "ended_at": "2026-01-01T00:00:00+00:00",
                "heartbeat_at": "2026-01-01T00:00:00+00:00",
                "lease_until": "2020-01-01T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    s.reconcile_leases()
    assert queue.released == []
