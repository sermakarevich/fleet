"""FR-20 / FR-27: Rate-limit threshold pauses spawning; config change respected."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

import pytest

from fleet.schemas import Event, Task

from tests.integration.conftest import (
    FakeClaudeCoder,
    MemoryQueue,
    fast_config,
    make_supervisor,
)

_USAGE_PCT = 92.0
_THRESHOLD = 90


def _task(tid: str) -> Task:
    return Task(id=tid, title=f"task-{tid}", description=None, status="open")


class _CountingCoder(FakeClaudeCoder):
    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self.spawn_count = 0

    def build_argv(self, task: Task, artifact_dir: Path) -> list[str]:
        self.spawn_count += 1
        return super().build_argv(task, artifact_dir)


def test_rate_limit_pauses_spawn(tmp_path: Path) -> None:
    """After first task reports usage_pct=92 > threshold=90, no new spawns. (FR-20)"""
    queue = MemoryQueue()
    for i in range(5):
        queue.add_task(_task(f"t-{i:03d}"))

    coder = _CountingCoder(
        scenario="rate_limit_info",
        FAKE_CLAUDE_USAGE_PCT=str(_USAGE_PCT),
    )
    config = fast_config(max_concurrent=3)
    sup = make_supervisor(tmp_path, queue, coder=coder, config=config)

    async def _run() -> None:
        sup_task = asyncio.create_task(sup.run())
        try:
            # Wait enough time for: first claim (1s) + subprocess run + second poll (1s)
            await asyncio.sleep(3.5)
        finally:
            await sup._shutdown()
            try:
                await asyncio.wait_for(sup_task, timeout=5.0)
            except asyncio.TimeoutError:
                sup_task.cancel()
                try:
                    await sup_task
                except (asyncio.CancelledError, Exception):
                    pass

    asyncio.run(_run())

    assert coder.spawn_count == 1, (
        f"expected 1 spawn after rate limit; got {coder.spawn_count}"
    )
    assert sup.rate_gauge.current_usage_pct == pytest.approx(_USAGE_PCT)


def test_rate_limit_resume_after_gauge_drop(tmp_path: Path) -> None:
    """Dropping gauge below threshold causes supervisor to resume spawning. (FR-20)"""
    queue = MemoryQueue()
    for i in range(3):
        queue.add_task(_task(f"t-{i:03d}"))

    coder = _CountingCoder(
        scenario="rate_limit_info",
        FAKE_CLAUDE_USAGE_PCT=str(_USAGE_PCT),
    )
    config = fast_config(max_concurrent=3)
    sup = make_supervisor(tmp_path, queue, coder=coder, config=config)

    async def _run() -> None:
        sup_task = asyncio.create_task(sup.run())
        try:
            # Let first task run, gauge rises to 92%
            await asyncio.sleep(3.0)

            spawned_before_drop = coder.spawn_count
            assert spawned_before_drop == 1, "should have 1 spawn before gauge drop"

            # Drop gauge below threshold
            sup.rate_gauge.update(Event(
                kind="rate_limit_info",
                raw={},
                ts=datetime.now(tz=timezone.utc),
                rate_info={"usage_pct": 10.0, "resets_at": None},
            ))
            # Wait for resume + additional spawns
            await asyncio.sleep(2.5)

            assert coder.spawn_count > spawned_before_drop, (
                "expected new spawns after gauge drop"
            )
        finally:
            await sup._shutdown()
            try:
                await asyncio.wait_for(sup_task, timeout=5.0)
            except asyncio.TimeoutError:
                sup_task.cancel()
                try:
                    await sup_task
                except (asyncio.CancelledError, Exception):
                    pass

    asyncio.run(_run())


