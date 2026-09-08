from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import structlog

from fleet.core.config import RuntimeConfig
from fleet.core.retry_policy import FAILURE_MAX_ROUNDS, NOCLOSE_MAX_ROUNDS
from fleet.core.task import Task, TaskOutcome, TaskOutcomeRecord
from fleet.orchestrator.supervisor import Supervisor
from fleet.state import attempts

# ---------------------------------------------------------------------------
# Test doubles
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
    def __init__(self, status: str = "open") -> None:
        self._status = status
        self.released: list[tuple[str, str]] = []
        self.blocked: list[tuple[str, str]] = []
        self.comments: list[tuple[str, str]] = []

    def claim_next(self, claimer_id, *, can_claim=None):
        return None

    def release(self, task_id, reason="", wait_sec=0):
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

    def set_bd_fields(self, task_id: str, body: dict) -> None:
        pass


def _make_supervisor(
    tmp_path: Path, queue: StubQueue, config: RuntimeConfig | None = None
) -> Supervisor:
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


def _history_outcomes(tmp_path: Path, task_id: str = "t-001") -> list[str]:
    return [
        e.get("outcome")
        for e in attempts.load_attempts(tmp_path / "tasks" / task_id)
        if e.get("outcome")
    ]


# ---------------------------------------------------------------------------
# FAILURE ladder: RELEASE with backoff until round 3, then BLOCK (history-based)
# ---------------------------------------------------------------------------


def test_failure_under_limit_calls_release(tmp_path: Path) -> None:
    queue = StubQueue(status="in_progress")
    s = _make_supervisor(tmp_path, queue)
    s._handle_outcome(
        _task(), _outcome(TaskOutcome.FAILURE, exit_code=1, reason="rc=1")
    )
    assert len(queue.released) == 1
    assert "rc=1" in queue.released[0][1]


def test_failure_under_limit_calls_comment(tmp_path: Path) -> None:
    queue = StubQueue(status="in_progress")
    s = _make_supervisor(tmp_path, queue)
    s._handle_outcome(_task(), _outcome(TaskOutcome.FAILURE, exit_code=1))
    assert len(queue.comments) == 1


def test_failure_under_limit_no_set_blocked(tmp_path: Path) -> None:
    queue = StubQueue(status="in_progress")
    s = _make_supervisor(tmp_path, queue)
    s._handle_outcome(_task(), _outcome(TaskOutcome.FAILURE, exit_code=1))
    assert len(queue.blocked) == 0


def test_failure_blocks_on_third_consecutive_round(tmp_path: Path) -> None:
    queue = StubQueue(status="in_progress")
    s = _make_supervisor(tmp_path, queue)
    for _ in range(FAILURE_MAX_ROUNDS - 1):
        s._handle_outcome(_task(), _outcome(TaskOutcome.FAILURE, exit_code=1))
    assert len(queue.blocked) == 0
    s._handle_outcome(_task(), _outcome(TaskOutcome.FAILURE, exit_code=1))
    assert len(queue.blocked) == 1


def test_failure_third_round_no_release(tmp_path: Path) -> None:
    queue = StubQueue(status="in_progress")
    s = _make_supervisor(tmp_path, queue)
    for _ in range(FAILURE_MAX_ROUNDS):
        s._handle_outcome(_task(), _outcome(TaskOutcome.FAILURE, exit_code=1))
    assert len(queue.released) == FAILURE_MAX_ROUNDS - 1


def test_failure_exhausted_reason_in_blocked(tmp_path: Path) -> None:
    queue = StubQueue(status="in_progress")
    s = _make_supervisor(tmp_path, queue)
    for _ in range(FAILURE_MAX_ROUNDS):
        s._handle_outcome(
            _task(), _outcome(TaskOutcome.FAILURE, exit_code=1, reason="crash")
        )
    assert "retry limit" in queue.blocked[0][1]


def test_failure_history_journaled(tmp_path: Path) -> None:
    queue = StubQueue(status="in_progress")
    s = _make_supervisor(tmp_path, queue)
    s._handle_outcome(_task(), _outcome(TaskOutcome.FAILURE, exit_code=1))
    assert _history_outcomes(tmp_path) == ["failure"]


# ---------------------------------------------------------------------------
# RATE_LIMIT outcome → _paused_until set, no history-driven block
# ---------------------------------------------------------------------------


def test_rate_limit_sets_paused_until(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("fleet.core.retry_policy.RATE_LIMIT_DEFAULT_SLEEP_SEC", 300)
    queue = StubQueue()
    s = _make_supervisor(tmp_path, queue)
    before = datetime.now(tz=UTC)
    s._handle_outcome(_task(), _outcome(TaskOutcome.RATE_LIMIT, resets_at=None))
    assert s._paused_until is not None
    assert s._paused_until > before


def test_rate_limit_paused_until_uses_resets_at_when_later(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr("fleet.core.retry_policy.RATE_LIMIT_DEFAULT_SLEEP_SEC", 5)
    queue = StubQueue()
    far_future = int(datetime.now(tz=UTC).timestamp()) + 9999
    s = _make_supervisor(tmp_path, queue)
    s._handle_outcome(_task(), _outcome(TaskOutcome.RATE_LIMIT, resets_at=far_future))
    assert s._paused_until is not None
    # paused_until should be >= far_future (resets_at wins)
    assert s._paused_until.timestamp() >= far_future


def test_rate_limit_releases_with_delay(tmp_path: Path) -> None:
    queue = StubQueue()
    s = _make_supervisor(tmp_path, queue)
    s._handle_outcome(_task(), _outcome(TaskOutcome.RATE_LIMIT))
    assert len(queue.released) == 1
    assert len(queue.blocked) == 0


def test_rate_limit_claim_loop_skips_while_paused(tmp_path: Path, monkeypatch) -> None:
    """After a RATE_LIMIT outcome, _paused_until is set and claim loop skips spawning."""
    monkeypatch.setattr("fleet.core.retry_policy.RATE_LIMIT_DEFAULT_SLEEP_SEC", 300)
    queue = StubQueue()
    s = _make_supervisor(tmp_path, queue)
    s._handle_outcome(_task(), _outcome(TaskOutcome.RATE_LIMIT))
    # Confirm paused_until is in the future
    assert s._paused_until > datetime.now(tz=UTC)


# ---------------------------------------------------------------------------
# CONTEXT_PRESSURE outcome → release (3rd consecutive blocks with split hint)
# ---------------------------------------------------------------------------


def test_context_pressure_calls_release(tmp_path: Path) -> None:
    queue = StubQueue(status="in_progress")
    s = _make_supervisor(tmp_path, queue)
    s._handle_outcome(_task(), _outcome(TaskOutcome.CONTEXT_PRESSURE))
    assert len(queue.released) == 1
    assert "context_pressure" in queue.released[0][1]


def test_context_pressure_third_round_blocks_with_split_hint(tmp_path: Path) -> None:
    queue = StubQueue(status="in_progress")
    s = _make_supervisor(tmp_path, queue)
    for _ in range(3):
        s._handle_outcome(_task(), _outcome(TaskOutcome.CONTEXT_PRESSURE))
    assert len(queue.blocked) == 1
    assert "split it" in queue.blocked[0][1]


# ---------------------------------------------------------------------------
# CONTEXT_PRESSURE when bead already closed → NOOP, no queue writes
# ---------------------------------------------------------------------------


def test_context_pressure_closed_bead_no_release(tmp_path: Path) -> None:
    queue = StubQueue(status="closed")
    s = _make_supervisor(tmp_path, queue)
    s._handle_outcome(_task(), _outcome(TaskOutcome.CONTEXT_PRESSURE))
    assert len(queue.released) == 0


def test_context_pressure_closed_bead_no_set_blocked(tmp_path: Path) -> None:
    queue = StubQueue(status="closed")
    s = _make_supervisor(tmp_path, queue)
    s._handle_outcome(_task(), _outcome(TaskOutcome.CONTEXT_PRESSURE))
    assert len(queue.blocked) == 0


# ---------------------------------------------------------------------------
# FAILURE when bead already closed → NOOP, no counter files
# ---------------------------------------------------------------------------


def test_failure_closed_bead_no_release(tmp_path: Path) -> None:
    queue = StubQueue(status="closed")
    s = _make_supervisor(tmp_path, queue)
    s._handle_outcome(_task(), _outcome(TaskOutcome.FAILURE, exit_code=1))
    assert len(queue.released) == 0


def test_failure_closed_bead_no_set_blocked(tmp_path: Path) -> None:
    queue = StubQueue(status="closed")
    s = _make_supervisor(tmp_path, queue)
    s._handle_outcome(_task(), _outcome(TaskOutcome.FAILURE, exit_code=1))
    assert len(queue.blocked) == 0


def test_failure_closed_bead_no_counter_files(tmp_path: Path) -> None:
    queue = StubQueue(status="closed")
    s = _make_supervisor(tmp_path, queue)
    s._handle_outcome(_task(), _outcome(TaskOutcome.FAILURE, exit_code=1))
    task_dir = s._task_dir_for(_task())
    assert not (task_dir / ".failures").exists()
    assert not (task_dir / ".noclose").exists()
    assert not (task_dir / ".stalls").exists()


# ---------------------------------------------------------------------------
# KILLED when bead already closed → no set_blocked, no comment
# ---------------------------------------------------------------------------


def test_killed_closed_bead_no_set_blocked(tmp_path: Path) -> None:
    queue = StubQueue(status="closed")
    s = _make_supervisor(tmp_path, queue)
    s._handle_outcome(_task(), _outcome(TaskOutcome.KILLED))
    assert len(queue.blocked) == 0


def test_killed_closed_bead_no_comment(tmp_path: Path) -> None:
    queue = StubQueue(status="closed")
    s = _make_supervisor(tmp_path, queue)
    s._handle_outcome(_task(), _outcome(TaskOutcome.KILLED))
    assert len(queue.comments) == 0


# ---------------------------------------------------------------------------
# SUCCESS with task still in_progress → release, journaled in history
# ---------------------------------------------------------------------------


def test_success_task_still_in_progress_calls_release(tmp_path: Path) -> None:
    queue = StubQueue(status="in_progress")
    s = _make_supervisor(tmp_path, queue)
    s._handle_outcome(_task(), _outcome(TaskOutcome.SUCCESS))
    assert len(queue.released) == 1
    assert "re-queueing" in queue.released[0][1]
    assert "#1/" in queue.released[0][1]


def test_success_task_already_closed_no_release(tmp_path: Path) -> None:
    queue = StubQueue(status="closed")
    s = _make_supervisor(tmp_path, queue)
    s._handle_outcome(_task(), _outcome(TaskOutcome.SUCCESS))
    assert len(queue.released) == 0


# ---------------------------------------------------------------------------
# NOCLOSE ladder: SUCCESS-without-close caps at NOCLOSE_MAX_ROUNDS (3)
# ---------------------------------------------------------------------------


def test_noclose_releases_below_limit_then_blocks(tmp_path: Path) -> None:
    queue = StubQueue(status="in_progress")
    s = _make_supervisor(tmp_path, queue)
    for _ in range(NOCLOSE_MAX_ROUNDS - 1):
        s._handle_outcome(_task(), _outcome(TaskOutcome.SUCCESS))
    assert len(queue.released) == NOCLOSE_MAX_ROUNDS - 1
    assert len(queue.blocked) == 0
    s._handle_outcome(_task(), _outcome(TaskOutcome.SUCCESS))
    assert len(queue.blocked) == 1
    assert "needs human review" in queue.blocked[0][1]


def test_noclose_exhausted_posts_comment(tmp_path: Path) -> None:
    queue = StubQueue(status="in_progress")
    s = _make_supervisor(tmp_path, queue)
    for _ in range(NOCLOSE_MAX_ROUNDS):
        s._handle_outcome(_task(), _outcome(TaskOutcome.SUCCESS))
    assert len(queue.comments) >= 1
    assert any("exhausted" in c[1] for c in queue.comments)


def test_no_counter_files_created(tmp_path: Path) -> None:
    queue = StubQueue(status="in_progress")
    s = _make_supervisor(tmp_path, queue)
    s._handle_outcome(_task(), _outcome(TaskOutcome.SUCCESS))
    task_dir = s._task_dir_for(_task())
    assert not (task_dir / ".noclose").exists()
    assert not (task_dir / ".failures").exists()


# ---------------------------------------------------------------------------
# BLOCKED_BY_AGENT outcome → no bd writes when the bead is already blocked
# ---------------------------------------------------------------------------


def test_blocked_by_agent_already_blocked_no_queue_writes(tmp_path: Path) -> None:
    queue = StubQueue(status="blocked")
    s = _make_supervisor(tmp_path, queue)
    s._handle_outcome(_task(), _outcome(TaskOutcome.BLOCKED_BY_AGENT))
    assert len(queue.released) == 0
    assert len(queue.blocked) == 0
    assert len(queue.comments) == 0


def test_blocked_by_agent_still_open_calls_set_blocked(tmp_path: Path) -> None:
    queue = StubQueue(status="open")
    s = _make_supervisor(tmp_path, queue)
    s._handle_outcome(_task(), _outcome(TaskOutcome.BLOCKED_BY_AGENT, reason="need creds"))
    assert queue.blocked == [("t-001", "need creds")]


# ---------------------------------------------------------------------------
# TERMINAL at spawn time → journaled + blocked at once
# ---------------------------------------------------------------------------


def _unpinned_supervisor(
    tmp_path: Path, queue: StubQueue, config: RuntimeConfig
) -> Supervisor:
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

    s._spawn_worker(_task("t-001"))

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

    s._spawn_worker(task)

    assert len(queue.blocked) == 1
    assert queue.blocked[0][0] == "t-002"
    assert "nope" in queue.blocked[0][1]
    assert "t-002" not in s.in_flight


def test_invalid_coder_writes_operator_comment(tmp_path: Path) -> None:
    queue = StubQueue()
    s = _unpinned_supervisor(tmp_path, queue, RuntimeConfig(coder="bogus_typo"))

    s._spawn_worker(_task("t-003"))

    assert len(queue.comments) == 1
    assert queue.comments[0][0] == "t-003"
    assert "bogus_typo" in queue.comments[0][1]


def test_invalid_coder_journals_terminal_attempt(tmp_path: Path) -> None:
    queue = StubQueue()
    s = _unpinned_supervisor(tmp_path, queue, RuntimeConfig(coder="bogus_typo"))
    s._spawn_worker(_task("t-004"))
    outcomes = _history_outcomes(tmp_path, "t-004")
    assert outcomes == ["terminal"]


def test_invalid_coder_does_not_freeze_task_meta(tmp_path: Path) -> None:
    """freeze_coder_model must NOT be called when resolution failed."""
    queue = StubQueue()
    frozen: list[tuple[str, str, str]] = []
    queue.freeze_coder_model = lambda tid, c, m: frozen.append((tid, c, m))  # type: ignore[attr-defined]
    s = _unpinned_supervisor(tmp_path, queue, RuntimeConfig(coder="bogus_typo"))

    s._spawn_worker(_task("t-004"))

    assert frozen == []


# ---------------------------------------------------------------------------
# Duplicate-claim guard: claim loop must not spawn a task already in flight
# ---------------------------------------------------------------------------


class _ClaimOnceQueue(StubQueue):
    """claim_next returns the given task on the first call, then None."""

    def __init__(self, task: Task) -> None:
        super().__init__()
        self._task = task
        self.claims = 0

    def claim_next(self, claimer_id, *, can_claim=None):
        self.claims += 1
        return self._task if self.claims == 1 else None


def _run_claim_loop_briefly(s: Supervisor, pre_in_flight: str | None) -> None:
    async def _run() -> None:
        fake_runner: asyncio.Task | None = None
        if pre_in_flight is not None:
            fake_runner = asyncio.create_task(asyncio.sleep(9999))
            s.in_flight[pre_in_flight] = fake_runner
        loop_task = asyncio.create_task(s._claim_and_spawn_loop())
        await asyncio.sleep(0.1)
        s._shutting_down = True
        await asyncio.wait_for(loop_task, timeout=2)
        if fake_runner is not None:
            fake_runner.cancel()

    asyncio.run(_run())


def test_claim_loop_skips_task_already_in_flight(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("fleet.orchestrator.claim.CLAIM_POLL_INTERVAL_SEC", 0.01)
    queue = _ClaimOnceQueue(_task("t-dup"))
    s = _make_supervisor(tmp_path, queue)
    spawned: list[str] = []
    s._spawn_worker = lambda t: spawned.append(t.id)  # type: ignore[method-assign]

    _run_claim_loop_briefly(s, pre_in_flight="t-dup")

    assert queue.claims >= 1
    assert spawned == []


def test_claim_loop_spawns_task_not_in_flight(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("fleet.orchestrator.claim.CLAIM_POLL_INTERVAL_SEC", 0.01)
    queue = _ClaimOnceQueue(_task("t-new"))
    s = _make_supervisor(tmp_path, queue)
    spawned: list[str] = []
    s._spawn_worker = lambda t: spawned.append(t.id)  # type: ignore[method-assign]

    _run_claim_loop_briefly(s, pre_in_flight=None)

    assert spawned == ["t-new"]


# ---------------------------------------------------------------------------
# Stall/timeout kill ladder: first KILLED releases, second blocks
# ---------------------------------------------------------------------------


def test_stall_killed_releases_first_then_blocks(tmp_path: Path) -> None:
    queue = StubQueue(status="in_progress")
    s = _make_supervisor(
        tmp_path,
        queue,
        config=RuntimeConfig(
            stall_warning_minutes=1, stall_action="kill", stall_block_after=2
        ),
    )
    task = _task("t-stall")

    # First stall-kill cycle: round 1 of 2 -> release for retry.
    s._stall_killed.add(task.id)
    s._handle_outcome(task, _outcome(TaskOutcome.KILLED, reason="stalled"))
    assert len(queue.released) == 1
    assert len(queue.blocked) == 0
    assert "#1/2" in queue.released[0][1]
    assert task.id not in s._stall_killed

    # Second stall-kill cycle: round 2 of 2 -> block for a human.
    s._stall_killed.add(task.id)
    s._handle_outcome(task, _outcome(TaskOutcome.KILLED, reason="stalled"))
    assert len(queue.released) == 1
    assert len(queue.blocked) == 1
    assert "needs human review" in queue.blocked[0][1]


def test_timeout_killed_shares_stall_ladder(tmp_path: Path) -> None:
    queue = StubQueue(status="in_progress")
    s = _make_supervisor(tmp_path, queue)
    task = _task("t-timeout")
    s._handle_outcome(task, _outcome(TaskOutcome.KILLED, reason="timeout"))
    assert len(queue.released) == 1
    s._handle_outcome(task, _outcome(TaskOutcome.KILLED, reason="timeout"))
    assert len(queue.blocked) == 1


def test_failure_release_writes_attempt_end_line(tmp_path: Path) -> None:
    """After a FAILURE outcome that releases, attempts.jsonl has an end line."""
    import json

    queue = StubQueue(status="in_progress")
    s = _make_supervisor(tmp_path, queue)
    s._handle_outcome(
        _task(), _outcome(TaskOutcome.FAILURE, exit_code=1, reason="rc=1")
    )
    assert len(queue.released) == 1
    attempts_path = tmp_path / "tasks" / "t-001" / "attempts.jsonl"
    assert attempts_path.exists()
    end_lines = [
        json.loads(line)
        for line in attempts_path.read_text(encoding="utf-8").splitlines()
        if line.strip() and json.loads(line).get("event") == "end"
    ]
    assert end_lines, "expected an end line in attempts.jsonl"
    assert end_lines[-1]["outcome"] == "failure"
    # The recorded action comes from the Decision just applied.
    assert end_lines[-1]["action"] == "release"
