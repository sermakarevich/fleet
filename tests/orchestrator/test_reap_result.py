from __future__ import annotations

import json
from pathlib import Path

from fleet.core.task import Task, TaskOutcome, TaskOutcomeRecord
from fleet.orchestrator.reap import handle_outcome
from fleet.orchestrator.supervisor import Supervisor
from fleet.state import attempts as attempts_mod
from fleet.state.paths import task_dir as _task_dir
from tests.conftest import make_running_worker, make_supervisor

# ---------------------------------------------------------------------------
# Test doubles (mirrors tests/orchestrator/test_supervisor_failures.py)
# ---------------------------------------------------------------------------


class StubCoder:
    name = "stub"

    def build_argv(self, task, task_dir, plan=None):
        return ["echo"]

    def env(self, task, task_dir):
        return {}

    def normalize_event(self, raw_line):
        return None


class StubQueue:
    def __init__(self, status: str = "in_progress") -> None:
        self._status = status
        self.released: list[tuple[str, str]] = []
        self.blocked: list[tuple[str, str]] = []
        self.closed: list[tuple[str, str]] = []
        self.comments: list[tuple[str, str]] = []

    def claim_next(self, claimer_id, *, can_claim=None):
        return None

    def release(self, task_id, reason="", wait_sec=0):
        self.released.append((task_id, reason))

    def set_blocked(self, task_id, reason):
        self.blocked.append((task_id, reason))

    def close(self, task_id, reason="completed"):
        self.closed.append((task_id, reason))

    def comment(self, task_id, body):
        self.comments.append((task_id, body))

    def get(self, task_id):
        return Task(id=task_id, title="T", description=None, status=self._status)

    def list_ready(self, limit=50):
        return []

    def set_bd_fields(self, task_id: str, body: dict) -> None:
        pass


def _make_supervisor(tmp_path: Path, queue: StubQueue) -> Supervisor:
    return make_supervisor(tmp_path, queue=queue, services=[], checks=[])


def _handle(
    s: Supervisor, task: Task, record: TaskOutcomeRecord, attempt_n: int | None = None
) -> None:
    """Fold one outcome through reap, opening a fresh attempt like spawn does."""

    if attempt_n is None:
        attempt_n = attempts_mod.record_start(
            s.state.task_dir_for(task.id), coder="c", model="m", worker="task.fresh"
        )
    worker = make_running_worker(task.id, None, task=task, attempt_n=attempt_n)
    handle_outcome(s.state, worker, record)


def _task(task_id: str = "t-001") -> Task:
    return Task(id=task_id, title="Test", description=None, status="in_progress")


def _write_result(tmp_path: Path, task_id: str, body: dict) -> None:
    task_dir = _task_dir(tmp_path, task_id)
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / "RESULT.json").write_text(json.dumps(body), encoding="utf-8")


def _rc0() -> TaskOutcomeRecord:
    return TaskOutcomeRecord(outcome=TaskOutcome.SUCCESS, exit_code=0, reason="")


# ---------------------------------------------------------------------------
# status=done -> fleet closes the bead itself
# ---------------------------------------------------------------------------


def test_status_done_closes_bead(tmp_path: Path) -> None:
    _write_result(tmp_path, "t-001", {"schema": 1, "status": "done", "summary": "shipped"})
    queue = StubQueue(status="in_progress")
    s = _make_supervisor(tmp_path, queue)
    _handle(s, _task(), _rc0())
    assert queue.closed == [("t-001", "shipped")]
    assert queue.released == []
    assert queue.blocked == []


def test_status_done_bead_already_closed_is_noop(tmp_path: Path) -> None:
    _write_result(tmp_path, "t-001", {"schema": 1, "status": "done", "summary": "shipped"})
    queue = StubQueue(status="closed")
    s = _make_supervisor(tmp_path, queue)
    _handle(s, _task(), _rc0())
    assert queue.closed == []
    assert queue.released == []
    assert queue.blocked == []


# ---------------------------------------------------------------------------
# status=partial -> RELEASE with next_step reason
# ---------------------------------------------------------------------------


def test_status_partial_releases_with_next_step(tmp_path: Path) -> None:
    _write_result(
        tmp_path,
        "t-001",
        {"schema": 1, "status": "partial", "summary": "half done", "next_step": "run tests"},
    )
    queue = StubQueue(status="in_progress")
    s = _make_supervisor(tmp_path, queue)
    _handle(s, _task(), _rc0())
    assert len(queue.released) == 1
    assert queue.released[0][1] == "run tests"
    assert queue.closed == []
    assert queue.blocked == []


# ---------------------------------------------------------------------------
# status=blocked -> BLOCK with blocked_reason
# ---------------------------------------------------------------------------


def test_status_blocked_blocks_with_reason(tmp_path: Path) -> None:
    _write_result(
        tmp_path,
        "t-001",
        {"schema": 1, "status": "blocked", "blocked_reason": "need creds"},
    )
    queue = StubQueue(status="in_progress")
    s = _make_supervisor(tmp_path, queue)
    _handle(s, _task(), _rc0())
    assert queue.blocked == [("t-001", "need creds")]
    assert queue.closed == []
    assert queue.released == []


# ---------------------------------------------------------------------------
# rc=0, no RESULT.json -> today's noclose path, comment mentions it
# ---------------------------------------------------------------------------


def test_no_result_json_releases_with_noclose_comment(tmp_path: Path) -> None:
    queue = StubQueue(status="in_progress")
    s = _make_supervisor(tmp_path, queue)
    _handle(s, _task(), _rc0())
    assert len(queue.released) == 1
    assert queue.closed == []
    assert "RESULT.json" in queue.comments[0][1]


# ---------------------------------------------------------------------------
# rc!=0 -> FAILURE regardless of RESULT.json; summary folded into comment
# ---------------------------------------------------------------------------


def test_failure_with_result_summary_in_comment(tmp_path: Path) -> None:
    _write_result(tmp_path, "t-001", {"schema": 1, "status": "done", "summary": "reached halfway"})
    queue = StubQueue(status="in_progress")
    s = _make_supervisor(tmp_path, queue)
    _handle(
        s,
        _task(),
        TaskOutcomeRecord(outcome=TaskOutcome.FAILURE, exit_code=1, reason="rc=1"),
    )
    assert len(queue.released) == 1
    assert "reached halfway" in queue.comments[0][1]


# ---------------------------------------------------------------------------
# reap snapshots STATE.md + RESULT.json into attempts/<n>, then unlinks live RESULT
# ---------------------------------------------------------------------------


def test_reap_snapshots_state_and_result_then_unlinks(tmp_path: Path) -> None:

    task_dir = _task_dir(tmp_path, "t-001")
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / "STATE.md").write_text("## Next\n- keep going\n", encoding="utf-8")
    _write_result(tmp_path, "t-001", {"schema": 1, "status": "done", "summary": "shipped"})
    attempts_mod.record_start(task_dir, coder="c", model="m", worker="task.fresh")

    queue = StubQueue(status="in_progress")
    s = _make_supervisor(tmp_path, queue)
    _handle(s, _task(), _rc0(), attempt_n=1)

    attempt_dir = task_dir / "attempts" / "1"
    assert (attempt_dir / "STATE.md").read_text(encoding="utf-8") == "## Next\n- keep going\n"
    assert (
        json.loads((attempt_dir / "RESULT.json").read_text(encoding="utf-8"))["summary"]
        == "shipped"
    )
    assert not (task_dir / "RESULT.json").exists()
    assert queue.closed == [("t-001", "shipped")]
