"""Tests for claim ticks and stall kills (unit under test: orchestrator claim/stall)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fleet.core.config import RuntimeConfig
from fleet.core.task import Task, TaskOutcome
from fleet.orchestrator import claim as claim_mod
from fleet.orchestrator.claim import Claim
from fleet.orchestrator.spawn import spawn_worker
from fleet.orchestrator.supervisor import Supervisor
from tests.conftest import make_running_worker, make_supervisor
from tests.orchestrator.conftest import (
    StubQueue,
    _handle,
    _history_outcomes,
    _make_supervisor,
    _outcome,
    _task,
)


def _unpinned_supervisor(tmp_path: Path, queue: StubQueue, config: RuntimeConfig) -> Supervisor:
    """Build a supervisor without a pinned coder so spawn runs the registry lookup."""
    return make_supervisor(tmp_path, queue=queue, config=config, services=[], checks=[])


class _ClaimOnceQueue(StubQueue):
    """claim_next returns the given task on the first call, then None."""

    def __init__(self, task: Task) -> None:
        super().__init__()
        self._task = task
        self.claims = 0

    def claim_next(self, claimer_id, *, can_claim=None):
        self.claims += 1
        return self._task if self.claims == 1 else None


class _ClaimTwiceQueue(_ClaimOnceQueue):
    """claim_next returns the task on the first two calls, then None."""

    def claim_next(self, claimer_id, *, can_claim=None):
        self.claims += 1
        return self._task if self.claims <= 2 else None


def test_invalid_default_coder_blocks_task(tmp_path: Path) -> None:
    queue = StubQueue()
    s = _unpinned_supervisor(tmp_path, queue, RuntimeConfig(coder="bogus_typo"))

    async def _run():
        return spawn_worker(s.state, _task("t-001"))

    assert asyncio.run(_run()) is None

    assert len(queue.blocked) == 1
    assert queue.blocked[0][0] == "t-001"
    assert "invalid coder" in queue.blocked[0][1]
    assert "bogus_typo" in queue.blocked[0][1]
    assert "t-001" not in s.state.running


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

    async def _run():
        return spawn_worker(s.state, task)

    assert asyncio.run(_run()) is None

    assert len(queue.blocked) == 1
    assert queue.blocked[0][0] == "t-002"
    assert "nope" in queue.blocked[0][1]
    assert "t-002" not in s.state.running


def test_invalid_coder_writes_operator_comment(tmp_path: Path) -> None:
    queue = StubQueue()
    s = _unpinned_supervisor(tmp_path, queue, RuntimeConfig(coder="bogus_typo"))

    async def _run():
        return spawn_worker(s.state, _task("t-003"))

    assert asyncio.run(_run()) is None

    assert len(queue.comments) == 1
    assert queue.comments[0][0] == "t-003"
    assert "bogus_typo" in queue.comments[0][1]


def test_invalid_coder_journals_terminal_attempt(tmp_path: Path) -> None:
    queue = StubQueue()
    s = _unpinned_supervisor(tmp_path, queue, RuntimeConfig(coder="bogus_typo"))

    async def _run():
        return spawn_worker(s.state, _task("t-004"))

    assert asyncio.run(_run()) is None
    outcomes = _history_outcomes(tmp_path, "t-004")
    assert outcomes == ["terminal"]


def test_invalid_coder_does_not_freeze_task_meta(tmp_path: Path) -> None:
    """freeze_coder_model must NOT be called when resolution failed."""
    queue = StubQueue()
    frozen: list[tuple[str, str, str]] = []
    queue.freeze_coder_model = lambda tid, c, m: frozen.append((tid, c, m))  # type: ignore[attr-defined]
    s = _unpinned_supervisor(tmp_path, queue, RuntimeConfig(coder="bogus_typo"))

    async def _run():
        return spawn_worker(s.state, _task("t-004"))

    assert asyncio.run(_run()) is None

    assert frozen == []


def test_claim_tick_skips_task_already_running(tmp_path: Path, monkeypatch) -> None:
    queue = _ClaimOnceQueue(_task("t-dup"))
    s = _make_supervisor(tmp_path, queue)
    s.state.running["t-dup"] = make_running_worker("t-dup", tmp_path)
    spawned: list[str] = []
    monkeypatch.setattr(claim_mod, "spawn_worker", lambda st, t: spawned.append(t.id))

    asyncio.run(Claim(interval_sec=0.01).tick(s.state))

    assert queue.claims >= 1
    assert spawned == []


def test_claim_tick_spawns_task_not_running(tmp_path: Path, monkeypatch) -> None:
    queue = _ClaimOnceQueue(_task("t-new"))
    s = _make_supervisor(tmp_path, queue)
    worker = make_running_worker("t-new", tmp_path)
    monkeypatch.setattr(claim_mod, "spawn_worker", lambda st, t: worker)

    asyncio.run(Claim(interval_sec=0.01).tick(s.state))

    assert s.state.running["t-new"] is worker


def test_claim_tick_survives_spawn_exception_and_releases(tmp_path: Path, monkeypatch) -> None:
    """Regression: an AttributeError inside spawn_worker (half-edited coder or
    config code) used to kill the claim loop silently, leaving the bead
    in_progress forever and the supervisor unable to claim anything else."""
    queue = _ClaimTwiceQueue(_task("t-boom"))
    s = _make_supervisor(tmp_path, queue)
    calls: list[str] = []

    def _boom(st, t):
        calls.append(t.id)
        raise AttributeError("'RuntimeConfig' object has no attribute 'opencode_context_limit'")

    monkeypatch.setattr(claim_mod, "spawn_worker", _boom)

    asyncio.run(Claim(interval_sec=0.01).tick(s.state))
    asyncio.run(Claim(interval_sec=0.01).tick(s.state))

    # The loop kept running: it came back for the second claim.
    assert calls == ["t-boom", "t-boom"]
    assert queue.released and queue.released[0][0] == "t-boom"
    assert "spawn failed" in queue.released[0][1]


def test_stall_killed_releases_first_then_blocks(tmp_path: Path) -> None:
    queue = StubQueue(status="in_progress")
    s = _make_supervisor(
        tmp_path,
        queue,
        config=RuntimeConfig(stall_warning_minutes=1, stall_action="kill"),
    )
    task = _task("t-stall")

    # First stall-kill cycle: round 1 of 2 -> release for retry.
    _handle(s, task, _outcome(TaskOutcome.KILLED, reason="stalled"))
    assert len(queue.released) == 1
    assert len(queue.blocked) == 0
    assert "#1/2" in queue.released[0][1]

    # Second stall-kill cycle: round 2 of 2 -> block for a human.
    _handle(s, task, _outcome(TaskOutcome.KILLED, reason="stalled"))
    assert len(queue.released) == 1
    assert len(queue.blocked) == 1
    assert "needs human review" in queue.blocked[0][1]


def test_timeout_killed_shares_stall_ladder(tmp_path: Path) -> None:
    queue = StubQueue(status="in_progress")
    s = _make_supervisor(tmp_path, queue)
    task = _task("t-timeout")
    _handle(s, task, _outcome(TaskOutcome.KILLED, reason="timeout"))
    assert len(queue.released) == 1
    _handle(s, task, _outcome(TaskOutcome.KILLED, reason="timeout"))
    assert len(queue.blocked) == 1


def test_failure_release_writes_attempt_end_line(tmp_path: Path) -> None:
    """After a FAILURE outcome that releases, attempts.jsonl has an end line."""

    queue = StubQueue(status="in_progress")
    s = _make_supervisor(tmp_path, queue)
    _handle(s, _task(), _outcome(TaskOutcome.FAILURE, exit_code=1, reason="rc=1"))
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
    # The recorded action comes from the RetryDecision just applied.
    assert end_lines[-1]["action"] == "release"
