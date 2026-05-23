"""FR-15 / FR-22: Context-pressure flag causes release without burning retries."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fleet.failures import failure_count
from fleet.schemas import Task

from tests.integration.conftest import (
    FakeClaudeCoder,
    MemoryQueue,
    fast_config,
    make_supervisor,
    run_until,
)


def _task(tid: str = "t-001") -> Task:
    return Task(id=tid, title="cp-task", description=None, status="open")


def test_context_pressure_release_no_failure(tmp_path: Path) -> None:
    """context_pressure releases task and does NOT increment failure_count. (FR-15/22)"""
    queue = MemoryQueue()
    queue.add_task(_task())

    coder = FakeClaudeCoder(scenario="context_pressure")
    config = fast_config()
    sup = make_supervisor(tmp_path, queue, coder=coder, config=config)

    done = asyncio.Event()

    def on_event(method: str, task_id: str) -> None:
        if method == "release":
            done.set()

    queue.add_listener(on_event)

    asyncio.run(run_until(sup, done, timeout=15.0))

    assert done.is_set()
    assert queue._tasks["t-001"].status == "open", "task should be back to open"

    release_reasons = [r for _, r in queue.released]
    assert any("context_pressure" in r for r in release_reasons)

    task_dir = tmp_path / "tasks" / "t-001"
    assert failure_count(task_dir) == 0, "context_pressure must not burn retries"


def test_context_pressure_flag_removed(tmp_path: Path) -> None:
    """.context_pressure flag is deleted by the runner after detection. (FR-15)"""
    queue = MemoryQueue()
    queue.add_task(_task())

    config = fast_config()
    task_dir = tmp_path / "tasks" / "t-001"

    coder = FakeClaudeCoder(scenario="context_pressure")
    sup = make_supervisor(tmp_path, queue, coder=coder, config=config)

    done = asyncio.Event()

    def on_event(method: str, task_id: str) -> None:
        if method == "release":
            done.set()

    queue.add_listener(on_event)

    asyncio.run(run_until(sup, done, timeout=15.0))

    assert not (task_dir / ".context_pressure").exists(), (
        ".context_pressure flag should be removed by runner"
    )


def test_context_pressure_then_success_events_append_only(tmp_path: Path) -> None:
    """After cp-release, second run appends events rather than overwriting. (FR-30)"""
    queue = MemoryQueue()
    queue.add_task(_task())

    # Run 1: context_pressure; run 2: clean_exit.
    # On clean_exit, task is still in_progress in MemoryQueue so gets re-queued.
    # We stop after the 2nd release.
    coder = FakeClaudeCoder(scenarios=["context_pressure", "clean_exit"])
    config = fast_config()
    sup = make_supervisor(tmp_path, queue, coder=coder, config=config)

    release_count = [0]
    done = asyncio.Event()

    def on_event(method: str, task_id: str) -> None:
        if method == "release":
            release_count[0] += 1
            if release_count[0] >= 2:
                done.set()

    queue.add_listener(on_event)

    asyncio.run(run_until(sup, done, timeout=20.0))

    task_dir = tmp_path / "tasks" / "t-001"
    events_path = task_dir / "events.jsonl"
    assert events_path.exists(), "events.jsonl should exist after both runs"

    lines = [json.loads(l) for l in events_path.read_text().splitlines() if l.strip()]
    assert len(lines) >= 2, (
        f"events from both runs should be appended; got {len(lines)} records"
    )

    assert failure_count(task_dir) == 0
