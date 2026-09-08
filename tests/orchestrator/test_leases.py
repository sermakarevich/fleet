"""Tests for orchestrator/leases.py::reconcile_leases.

The lease is the liveness proof of a running attempt: while the coder
subprocess lives, workers/llm_session.py refreshes run.json's
heartbeat_at/lease_until every HEARTBEAT_SEC. Reclaim must be safe
first — it releases a bead only when the lease is stale AND the pid is
provably dead (or on another host), and never touches human-claimed
beads or live pids.
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fleet.core.limits import HEARTBEAT_SEC
from fleet.core.task import Task
from fleet.orchestrator.leases import lease_is_stale
from fleet.state import attempts
from tests.conftest import make_running_worker
from tests.helpers.task_dir import make_attempt
from tests.orchestrator.test_supervisor_failures import (
    StubQueue,
    _make_supervisor,
    _task,
)


class FakeLog:
    """Recording stand-in for a structlog bound logger."""

    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict]] = []

    def _rec(self, level: str, event: str, kw: dict) -> None:
        self.events.append((level, event, kw))

    def info(self, event: str, **kw) -> None:
        self._rec("info", event, kw)

    def warning(self, event: str, **kw) -> None:
        self._rec("warning", event, kw)

    def error(self, event: str, **kw) -> None:
        self._rec("error", event, kw)

    def exception(self, event: str, **kw) -> None:
        self._rec("exception", event, kw)

    def bind(self, **kw) -> FakeLog:
        return self

    def warnings(self, event: str) -> list[dict]:
        return [kw for lvl, evt, kw in self.events if lvl == "warning" and evt == event]


class LeaseQueue(StubQueue):
    """StubQueue with controllable list_in_progress output."""

    def __init__(self, in_progress: list[Task]) -> None:
        super().__init__(status="in_progress")
        self._in_progress = in_progress

    def list_in_progress(self, limit: int = 500) -> list[Task]:
        return self._in_progress[:limit]


def _dead_pid() -> int:
    """Pid of an already-reaped process: guaranteed not alive."""
    proc = subprocess.Popen(["true"])
    proc.wait()
    return proc.pid


def _iso_now_plus(seconds: float) -> str:
    return (datetime.now(tz=UTC) + timedelta(seconds=seconds)).isoformat()


def _write_run_json(attempt_dir: Path, payload: dict) -> None:
    (attempt_dir / "run.json").write_text(json.dumps(payload), encoding="utf-8")


def _setup_attempt(tmp_path: Path, s, task: Task, payload: dict) -> Path:
    """Create attempts.jsonl + attempts/1/run.json for *task*; return task dir."""
    task_dir = s._task_dir_for(task)
    attempt_dir = make_attempt(task_dir, 1)
    _write_run_json(attempt_dir, payload)
    return task_dir


def _lease_payload(pid: int, lease_offset_sec: float, **extra) -> dict:
    now = datetime.now(tz=UTC)
    return {
        "pid": pid,
        "supervisor_pid": os.getpid(),
        "started_at": (now - timedelta(hours=1)).isoformat(),
        "heartbeat_at": (now + timedelta(seconds=lease_offset_sec - 3 * HEARTBEAT_SEC)).isoformat(),
        "lease_until": (now + timedelta(seconds=lease_offset_sec)).isoformat(),
        **extra,
    }


def _end_lines(task_dir: Path) -> list[dict]:
    return [e for e in attempts.load_attempts(task_dir) if e.get("ended_at")]


# ---------------------------------------------------------------------------
# lease_is_stale: stale only past one full heartbeat of slack
# ---------------------------------------------------------------------------


def test_lease_stale_boundary() -> None:
    now = datetime.now(tz=UTC)
    assert not lease_is_stale(now, now)
    assert not lease_is_stale(now + timedelta(seconds=10), now)
    assert not lease_is_stale(None, now)
    assert lease_is_stale(
        now - timedelta(seconds=HEARTBEAT_SEC + 1), now
    )
    assert not lease_is_stale(
        now - timedelta(seconds=HEARTBEAT_SEC - 1), now
    )


# ---------------------------------------------------------------------------
# reconcile_leases cases
# ---------------------------------------------------------------------------


def test_fresh_lease_no_action(tmp_path: Path) -> None:
    task = _task("t-lease-fresh")
    queue = LeaseQueue([task])
    s = _make_supervisor(tmp_path, queue)
    task_dir = _setup_attempt(
        tmp_path, s, task, _lease_payload(_dead_pid(), lease_offset_sec=300)
    )
    s.reconcile_leases()
    assert queue.released == []
    assert _end_lines(task_dir) == []


def test_stale_lease_dead_pid_released_once(tmp_path: Path) -> None:
    task = _task("t-lease-dead")
    queue = LeaseQueue([task])
    s = _make_supervisor(tmp_path, queue)
    task_dir = _setup_attempt(
        tmp_path, s, task, _lease_payload(_dead_pid(), lease_offset_sec=-300)
    )
    s.reconcile_leases()
    assert len(queue.released) == 1
    assert queue.released[0][0] == "t-lease-dead"
    assert "lease expired" in queue.released[0][1]
    ended = _end_lines(task_dir)
    assert len(ended) == 1
    assert ended[0]["outcome"] == "killed"
    assert ended[0]["reason"] == "lease expired"
    assert ended[0]["action"] == "release"
    # A second sweep must not release or journal again: the end line marks
    # the attempt closed, so the bead is the claim loop's business now.
    s.reconcile_leases()
    assert len(queue.released) == 1
    assert len(_end_lines(task_dir)) == 1


def test_stale_lease_alive_pid_warns_only(tmp_path: Path) -> None:
    task = _task("t-lease-alive")
    queue = LeaseQueue([task])
    s = _make_supervisor(tmp_path, queue)
    log = FakeLog()
    s._log = log  # type: ignore[assignment]
    _setup_attempt(
        tmp_path,
        s,
        task,
        _lease_payload(os.getpid(), lease_offset_sec=-300),
    )
    s.reconcile_leases()
    assert queue.released == []
    assert len(log.warnings("lease_stale_pid_alive")) == 1


def test_human_claimed_bead_without_task_dir_untouched(tmp_path: Path) -> None:
    task = _task("t-lease-human")
    queue = LeaseQueue([task])
    s = _make_supervisor(tmp_path, queue)
    log = FakeLog()
    s._log = log  # type: ignore[assignment]
    # No task dir at all: claimed by a human via `bd update --claim`.
    s.reconcile_leases()
    assert queue.released == []
    assert any(
        evt in ("lease_no_attempt_dir", "lease_no_run_json")
        for _, evt, _ in log.events
    )


def test_running_set_membership_untouched(tmp_path: Path) -> None:
    task = _task("t-lease-running")
    queue = LeaseQueue([task])
    s = _make_supervisor(tmp_path, queue)
    _setup_attempt(
        tmp_path, s, task, _lease_payload(_dead_pid(), lease_offset_sec=-300)
    )
    s.state.running["t-lease-running"] = make_running_worker("t-lease-running", tmp_path)
    try:
        s.reconcile_leases()
    finally:
        s.state.running.pop("t-lease-running", None)
    assert queue.released == []


def test_run_json_without_heartbeat_keys_untouched(tmp_path: Path) -> None:
    """Old-format run.json (pid only, no lease) can prove nothing: no touch."""
    task = _task("t-lease-nobeat")
    queue = LeaseQueue([task])
    s = _make_supervisor(tmp_path, queue)
    _setup_attempt(tmp_path, s, task, {"pid": _dead_pid()})
    s.reconcile_leases()
    assert queue.released == []


def test_stale_lease_other_host_reclaimed(tmp_path: Path) -> None:
    """A lease recorded on another host can never be ours: pid probe is moot."""
    task = _task("t-lease-remote")
    queue = LeaseQueue([task])
    s = _make_supervisor(tmp_path, queue)
    payload = _lease_payload(os.getpid(), lease_offset_sec=-300)
    payload["host"] = "definitely-not-this-host"
    _setup_attempt(tmp_path, s, task, payload)
    s.reconcile_leases()
    assert len(queue.released) == 1
    assert queue.released[0][0] == "t-lease-remote"


def test_list_failure_never_raises(tmp_path: Path) -> None:
    class _BoomQueue(StubQueue):
        def list_in_progress(self, limit: int = 500) -> list[Task]:
            raise RuntimeError("bd is down")

    s = _make_supervisor(tmp_path, _BoomQueue())
    s.reconcile_leases()  # must not raise
