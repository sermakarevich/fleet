"""FR-07 / FR-08 / FR-09: Task failure, retry, and retry-limit exhaustion."""
from __future__ import annotations

import asyncio
from pathlib import Path

from fleet.core.retry_policy import rounds_for_history
from fleet.core.task import Task
from fleet.state.attempts import load_attempts
from fleet.state.paths import attempt_dir_path
from tests.integration.conftest import (
    FakeClaudeCoder,
    MemoryQueue,
    fast_config,
    make_supervisor,
    run_until,
)


def _task(tid: str = "t-001") -> Task:
    return Task(id=tid, title="crash-task", description=None, status="open")


# ---------------------------------------------------------------------------
# Scenario 1: plain crash repeated → set_blocked after retry_limit
# ---------------------------------------------------------------------------


def test_failure_retry_exhaustion(tmp_path: Path) -> None:
    """Task fails 3 times → set_blocked; comments record each failure. (FR-07/08)"""
    queue = MemoryQueue()
    queue.add_task(_task())

    config = fast_config()
    coder = FakeClaudeCoder(scenario="crash")
    sup = make_supervisor(tmp_path, queue, coder=coder, config=config)

    done = asyncio.Event()

    def on_event(method: str, task_id: str) -> None:
        if method == "set_blocked" and task_id == "t-001":
            done.set()

    queue.add_listener(on_event)

    asyncio.run(run_until(sup, done, timeout=20.0))

    assert len(queue.blocked) == 1, "task should be blocked after retry exhaustion"
    assert queue.blocked[0][0] == "t-001"
    assert "retry limit" in queue.blocked[0][1]

    task_dir = tmp_path / "tasks" / "t-001"
    assert rounds_for_history(load_attempts(task_dir))["failure"] == 3

    # All three failures produce a supervisor comment (two releases + exhaustion)
    assert len(queue.comments) == 3
    for _, body in queue.comments:
        assert "fleet" in body.lower() or "failure" in body.lower()


def test_failure_transitions(tmp_path: Path) -> None:
    """Status transitions: open → in_progress → open → in_progress → blocked. (FR-08)"""
    queue = MemoryQueue()
    queue.add_task(_task())

    transitions: list[tuple[str, str]] = []

    def on_event(method: str, task_id: str) -> None:
        transitions.append((method, queue._tasks.get(task_id, _task()).status))

    queue.add_listener(on_event)

    config = fast_config()
    coder = FakeClaudeCoder(scenario="crash")
    sup = make_supervisor(tmp_path, queue, coder=coder, config=config)

    done = asyncio.Event()

    def _done(m: str, _: str) -> None:
        if m == "set_blocked":
            done.set()

    queue.add_listener(_done)

    asyncio.run(run_until(sup, done, timeout=20.0))

    methods = [m for m, _ in transitions]
    assert "claim" in methods
    assert "release" in methods
    assert "set_blocked" in methods


# ---------------------------------------------------------------------------
# Scenario 2: mixed outcomes — non-failure events don't burn retries (FR-09)
# ---------------------------------------------------------------------------


def test_non_failures_dont_burn_retries(tmp_path: Path) -> None:
    """rate_limit + context_pressure don't count as failures; crash(×3) exhausts limit."""
    queue = MemoryQueue()
    queue.add_task(_task())

    # Run sequence: rate_limit_rejected, context_pressure, crash, crash, crash
    # Only crashes count → after 3 crashes, the failure ladder (3) is exhausted
    coder = FakeClaudeCoder(
        scenarios=["rate_limit_rejected", "context_pressure", "crash", "crash", "crash"],
    )
    config = fast_config()
    sup = make_supervisor(tmp_path, queue, coder=coder, config=config)

    done = asyncio.Event()

    def on_event(method: str, task_id: str) -> None:
        if method == "set_blocked":
            done.set()

    queue.add_listener(on_event)

    asyncio.run(run_until(sup, done, timeout=30.0))

    task_dir = tmp_path / "tasks" / "t-001"
    assert rounds_for_history(load_attempts(task_dir))["failure"] == 3, "exactly 3 crash-failures"
    # Each attempt now writes its own attempts/<n>/log.jsonl; sum across all
    # attempt dirs (one per run) instead of one shared task-root file.
    starts = 0
    for row in load_attempts(task_dir):
        log_path = attempt_dir_path(task_dir, row["n"]) / "log.jsonl"
        if not log_path.exists():
            continue
        starts += sum(
            1
            for line in log_path.read_text().splitlines()
            if line and '"subprocess_started"' in line
        )
    assert starts >= 3, f"at least 3 subprocess_started entries expected, got {starts}"
    assert len(queue.blocked) == 1
    assert queue._tasks["t-001"].status == "blocked"
