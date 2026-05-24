from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import structlog

from fleet.failures import failure_count
from fleet.schemas import RuntimeConfig, Task, TaskOutcome, TaskOutcomeRecord
from fleet.supervisor import Supervisor


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class StubCoder:
    name = "stub"

    def build_argv(self, task, task_dir):
        return ["echo"]

    def env(self, task, task_dir):
        return {}

    def normalize_event(self, raw_line):
        return None


class StubQueue:
    def __init__(self, status: str = "open") -> None:
        self._status = status
        self.released: list[tuple[str, str]] = []
        self.blocked: list[tuple[str, str]] = []
        self.comments: list[tuple[str, str]] = []

    def claim_next(self, claimer_id):
        return None

    def release(self, task_id, reason=""):
        self.released.append((task_id, reason))

    def set_blocked(self, task_id, reason):
        self.blocked.append((task_id, reason))

    def close(self, task_id, reason="completed"):
        pass

    def comment(self, task_id, body):
        self.comments.append((task_id, body))

    def get(self, task_id):
        return Task(id=task_id, title="T", description=None, status=self._status)

    def list_ready(self, limit=50):
        return []


def _make_supervisor(tmp_path: Path, queue: StubQueue, config: RuntimeConfig | None = None) -> Supervisor:
    s = Supervisor(
        coder=StubCoder(),
        queue=queue,
        runtime_toml_path=tmp_path / "runtime.toml",
        project_root=tmp_path,
        log=structlog.get_logger(),
    )
    if config is not None:
        s.config = config
    return s


def _task(task_id: str = "t-001", status: str = "in_progress") -> Task:
    return Task(id=task_id, title="Test", description=None, status=status)


def _outcome(
    outcome: TaskOutcome,
    exit_code: int = 0,
    reason: str = "",
    resets_at: int | None = None,
    stderr_tail: str | None = None,
) -> TaskOutcomeRecord:
    return TaskOutcomeRecord(
        outcome=outcome,
        exit_code=exit_code,
        reason=reason,
        resets_at=resets_at,
        stderr_tail=stderr_tail,
    )


# ---------------------------------------------------------------------------
# FAILURE under retry_limit → release + comment, no set_blocked
# ---------------------------------------------------------------------------


def test_failure_under_limit_calls_release(tmp_path: Path) -> None:
    queue = StubQueue()
    s = _make_supervisor(tmp_path, queue, config=RuntimeConfig(retry_limit=3))
    s._handle_outcome(_task(), _outcome(TaskOutcome.FAILURE, exit_code=1, reason="rc=1"))
    assert len(queue.released) == 1
    assert "rc=1" in queue.released[0][1]


def test_failure_under_limit_calls_comment(tmp_path: Path) -> None:
    queue = StubQueue()
    s = _make_supervisor(tmp_path, queue, config=RuntimeConfig(retry_limit=3))
    s._handle_outcome(_task(), _outcome(TaskOutcome.FAILURE, exit_code=1))
    assert len(queue.comments) == 1


def test_failure_under_limit_no_set_blocked(tmp_path: Path) -> None:
    queue = StubQueue()
    s = _make_supervisor(tmp_path, queue, config=RuntimeConfig(retry_limit=3))
    s._handle_outcome(_task(), _outcome(TaskOutcome.FAILURE, exit_code=1))
    assert len(queue.blocked) == 0


# ---------------------------------------------------------------------------
# FAILURE at retry_limit → set_blocked + comment, no release
# ---------------------------------------------------------------------------


def test_failure_at_limit_calls_set_blocked(tmp_path: Path) -> None:
    queue = StubQueue()
    s = _make_supervisor(tmp_path, queue, config=RuntimeConfig(retry_limit=2))
    s._handle_outcome(_task(), _outcome(TaskOutcome.FAILURE, exit_code=1))
    s._handle_outcome(_task(), _outcome(TaskOutcome.FAILURE, exit_code=1))
    assert len(queue.blocked) == 1


def test_failure_at_limit_no_release(tmp_path: Path) -> None:
    queue = StubQueue()
    s = _make_supervisor(tmp_path, queue, config=RuntimeConfig(retry_limit=1))
    s._handle_outcome(_task(), _outcome(TaskOutcome.FAILURE, exit_code=1))
    assert len(queue.released) == 0


def test_failure_at_limit_calls_comment(tmp_path: Path) -> None:
    queue = StubQueue()
    s = _make_supervisor(tmp_path, queue, config=RuntimeConfig(retry_limit=1))
    s._handle_outcome(_task(), _outcome(TaskOutcome.FAILURE, exit_code=1))
    assert len(queue.comments) == 1


def test_failure_exhausted_reason_in_blocked(tmp_path: Path) -> None:
    queue = StubQueue()
    s = _make_supervisor(tmp_path, queue, config=RuntimeConfig(retry_limit=1))
    s._handle_outcome(_task(), _outcome(TaskOutcome.FAILURE, exit_code=1, reason="crash"))
    assert "retry limit" in queue.blocked[0][1]


# ---------------------------------------------------------------------------
# RATE_LIMIT outcome → _paused_until set, failure counter not incremented
# ---------------------------------------------------------------------------


def test_rate_limit_sets_paused_until(tmp_path: Path) -> None:
    queue = StubQueue()
    s = _make_supervisor(tmp_path, queue, config=RuntimeConfig(rate_limit_default_sleep_sec=300))
    before = datetime.now(tz=timezone.utc)
    s._handle_outcome(_task(), _outcome(TaskOutcome.RATE_LIMIT, resets_at=None))
    assert s._paused_until is not None
    assert s._paused_until > before


def test_rate_limit_paused_until_uses_resets_at_when_later(tmp_path: Path) -> None:
    queue = StubQueue()
    far_future = int(datetime.now(tz=timezone.utc).timestamp()) + 9999
    s = _make_supervisor(tmp_path, queue, config=RuntimeConfig(rate_limit_default_sleep_sec=5))
    s._handle_outcome(_task(), _outcome(TaskOutcome.RATE_LIMIT, resets_at=far_future))
    assert s._paused_until is not None
    # paused_until should be >= far_future (resets_at wins)
    assert s._paused_until.timestamp() >= far_future


def test_rate_limit_does_not_increment_failure_count(tmp_path: Path) -> None:
    queue = StubQueue()
    s = _make_supervisor(tmp_path, queue)
    s._handle_outcome(_task(), _outcome(TaskOutcome.RATE_LIMIT))
    assert failure_count(s._task_dir_for(_task())) == 0


def test_rate_limit_claim_loop_skips_while_paused(tmp_path: Path) -> None:
    """After a RATE_LIMIT outcome, _paused_until is set and claim loop skips spawning."""
    from datetime import timedelta

    queue = StubQueue()
    s = _make_supervisor(tmp_path, queue, config=RuntimeConfig(rate_limit_default_sleep_sec=300))
    s._handle_outcome(_task(), _outcome(TaskOutcome.RATE_LIMIT))
    # Confirm paused_until is in the future
    assert s._paused_until > datetime.now(tz=timezone.utc)


# ---------------------------------------------------------------------------
# CONTEXT_PRESSURE outcome → release, failure counter not incremented
# ---------------------------------------------------------------------------


def test_context_pressure_calls_release(tmp_path: Path) -> None:
    queue = StubQueue()
    s = _make_supervisor(tmp_path, queue)
    s._handle_outcome(_task(), _outcome(TaskOutcome.CONTEXT_PRESSURE))
    assert len(queue.released) == 1
    assert "context_pressure" in queue.released[0][1]


def test_context_pressure_does_not_increment_failure_count(tmp_path: Path) -> None:
    queue = StubQueue()
    s = _make_supervisor(tmp_path, queue)
    s._handle_outcome(_task(), _outcome(TaskOutcome.CONTEXT_PRESSURE))
    assert failure_count(s._task_dir_for(_task())) == 0


# ---------------------------------------------------------------------------
# SUCCESS with task still in_progress → release, no failure increment
# ---------------------------------------------------------------------------


def test_success_task_still_in_progress_calls_release(tmp_path: Path) -> None:
    queue = StubQueue(status="in_progress")
    s = _make_supervisor(tmp_path, queue)
    s._handle_outcome(_task(), _outcome(TaskOutcome.SUCCESS))
    assert len(queue.released) == 1
    assert "re-queueing" in queue.released[0][1]


def test_success_task_already_closed_no_release(tmp_path: Path) -> None:
    queue = StubQueue(status="closed")
    s = _make_supervisor(tmp_path, queue)
    s._handle_outcome(_task(), _outcome(TaskOutcome.SUCCESS))
    assert len(queue.released) == 0


def test_success_does_not_increment_failure_count(tmp_path: Path) -> None:
    queue = StubQueue(status="in_progress")
    s = _make_supervisor(tmp_path, queue)
    s._handle_outcome(_task(), _outcome(TaskOutcome.SUCCESS))
    assert failure_count(s._task_dir_for(_task())) == 0


# ---------------------------------------------------------------------------
# BLOCKED_BY_AGENT outcome → no bd writes, no failure increment
# ---------------------------------------------------------------------------


def test_blocked_by_agent_no_queue_writes(tmp_path: Path) -> None:
    queue = StubQueue()
    s = _make_supervisor(tmp_path, queue)
    s._handle_outcome(_task(), _outcome(TaskOutcome.BLOCKED_BY_AGENT))
    assert len(queue.released) == 0
    assert len(queue.blocked) == 0
    assert len(queue.comments) == 0


def test_blocked_by_agent_no_failure_increment(tmp_path: Path) -> None:
    queue = StubQueue()
    s = _make_supervisor(tmp_path, queue)
    s._handle_outcome(_task(), _outcome(TaskOutcome.BLOCKED_BY_AGENT))
    assert failure_count(s._task_dir_for(_task())) == 0


# ---------------------------------------------------------------------------
# Invalid coder at spawn time → set_blocked + comment, no runner created
# ---------------------------------------------------------------------------


def _unpinned_supervisor(tmp_path: Path, queue: StubQueue, config: RuntimeConfig) -> Supervisor:
    """Build a supervisor without a pinned coder so _resolve_coder runs the registry lookup."""
    s = Supervisor(
        queue=queue,
        runtime_toml_path=tmp_path / "runtime.toml",
        project_root=tmp_path,
        log=structlog.get_logger(),
    )
    s.config = config
    return s


def test_invalid_default_coder_blocks_task(tmp_path: Path) -> None:
    queue = StubQueue()
    s = _unpinned_supervisor(tmp_path, queue, RuntimeConfig(coder="bogus_typo"))

    s._spawn_runner(_task("t-001"))

    assert len(queue.blocked) == 1
    assert queue.blocked[0][0] == "t-001"
    assert "invalid coder" in queue.blocked[0][1]
    assert "bogus_typo" in queue.blocked[0][1]
    assert "t-001" not in s.in_flight


def test_invalid_task_override_blocks_task(tmp_path: Path) -> None:
    """A per-task coder override that's invalid blocks even when the default is valid."""
    queue = StubQueue()
    s = _unpinned_supervisor(tmp_path, queue, RuntimeConfig(coder="claude"))
    task = Task(
        id="t-002",
        title="X",
        description=None,
        status="in_progress",
        coder="nope",
    )

    s._spawn_runner(task)

    assert len(queue.blocked) == 1
    assert queue.blocked[0][0] == "t-002"
    assert "nope" in queue.blocked[0][1]
    assert "t-002" not in s.in_flight


def test_invalid_coder_writes_operator_comment(tmp_path: Path) -> None:
    queue = StubQueue()
    s = _unpinned_supervisor(tmp_path, queue, RuntimeConfig(coder="bogus_typo"))

    s._spawn_runner(_task("t-003"))

    assert len(queue.comments) == 1
    assert queue.comments[0][0] == "t-003"
    assert "bogus_typo" in queue.comments[0][1]
    assert "runtime.toml" in queue.comments[0][1]


def test_invalid_coder_does_not_freeze_task_meta(tmp_path: Path) -> None:
    """freeze_coder_model must NOT be called when resolution failed."""
    queue = StubQueue()
    frozen: list[tuple[str, str, str]] = []
    queue.freeze_coder_model = lambda tid, c, m: frozen.append((tid, c, m))  # type: ignore[attr-defined]
    s = _unpinned_supervisor(tmp_path, queue, RuntimeConfig(coder="bogus_typo"))

    s._spawn_runner(_task("t-004"))

    assert frozen == []
