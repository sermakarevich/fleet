"""FR-21: Hard rate-limit rejection terminates subprocess and pauses spawning."""
from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest

from fleet.schemas import Task

from tests.integration.conftest import (
    FakeClaudeCoder,
    MemoryQueue,
    fast_config,
    make_supervisor,
    run_until,
)


def _task(tid: str = "t-001") -> Task:
    return Task(id=tid, title="rl-rejected-task", description=None, status="open")


def test_rate_limit_rejected_terminates_subprocess(tmp_path: Path) -> None:
    """On 429, subprocess is SIGTERM'd promptly (< 3s wall time). (FR-21)"""
    queue = MemoryQueue()
    queue.add_task(_task())

    start_times: dict[str, float] = {}
    end_times: dict[str, float] = {}

    class TimingCoder(FakeClaudeCoder):
        def build_argv(self, task: Task, artifact_dir: Path) -> list[str]:
            start_times[task.id] = time.monotonic()
            return super().build_argv(task, artifact_dir)

    coder = TimingCoder(scenario="rate_limit_rejected")
    config = fast_config()
    sup = make_supervisor(tmp_path, queue, coder=coder, config=config)

    done = asyncio.Event()

    def on_event(method: str, task_id: str) -> None:
        if method == "release":
            end_times[task_id] = time.monotonic()
            done.set()

    queue.add_listener(on_event)

    asyncio.run(run_until(sup, done, timeout=15.0))

    assert done.is_set(), "rate_limit_rejected should have released the task"
    assert "t-001" in end_times, "task should have been released"
    wall_time = end_times["t-001"] - start_times.get("t-001", end_times["t-001"])
    assert wall_time < 4.0, f"subprocess should be terminated within 4s; took {wall_time:.1f}s"

    # Task returned to open
    assert queue._tasks["t-001"].status == "open"


def test_rate_limit_rejected_sets_paused_until(tmp_path: Path) -> None:
    """After 429, supervisor _paused_until is set so no new spawns happen. (FR-21)"""
    queue = MemoryQueue()
    queue.add_task(_task())

    coder = FakeClaudeCoder(scenario="rate_limit_rejected")
    config = fast_config()
    sup = make_supervisor(tmp_path, queue, coder=coder, config=config)

    done = asyncio.Event()

    def on_event(method: str, task_id: str) -> None:
        if method == "release":
            done.set()

    queue.add_listener(on_event)

    asyncio.run(run_until(sup, done, timeout=15.0))

    assert sup._paused_until is not None, "_paused_until should be set after 429"


def test_rate_limit_rejected_with_resets_at(tmp_path: Path) -> None:
    """resetsAt from 429 response is used to set _paused_until. (FR-21)"""
    import time as _time

    queue = MemoryQueue()
    queue.add_task(_task())

    future_ts = int(_time.time()) + 30
    coder = FakeClaudeCoder(
        scenario="rate_limit_rejected",
        FAKE_CLAUDE_RESETS_AT=str(future_ts),
    )
    config = fast_config()
    sup = make_supervisor(tmp_path, queue, coder=coder, config=config)

    done = asyncio.Event()

    def on_event(method: str, task_id: str) -> None:
        if method == "release":
            done.set()

    queue.add_listener(on_event)

    asyncio.run(run_until(sup, done, timeout=15.0))

    assert sup._paused_until is not None
    assert sup._paused_until.timestamp() >= future_ts


def test_rate_limit_rejected_fallback_no_resets_at(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Without resetsAt, supervisor falls back to rate_limit_default_sleep_sec. (FR-21)"""
    sleep_sec = 45
    monkeypatch.setattr("fleet.supervisor.RATE_LIMIT_DEFAULT_SLEEP_SEC", sleep_sec)

    queue = MemoryQueue()
    queue.add_task(_task())

    coder = FakeClaudeCoder(scenario="rate_limit_rejected")
    config = fast_config()
    sup = make_supervisor(tmp_path, queue, coder=coder, config=config)

    done = asyncio.Event()

    def on_event(method: str, task_id: str) -> None:
        if method == "release":
            done.set()

    queue.add_listener(on_event)

    asyncio.run(run_until(sup, done, timeout=15.0))

    assert sup._paused_until is not None
    # paused_until should be at least ~sleep_sec seconds in the future
    import time as _time
    from datetime import datetime, timezone
    expected_min = datetime.fromtimestamp(
        _time.time() + sleep_sec - 2, tz=timezone.utc
    )
    assert sup._paused_until >= expected_min
