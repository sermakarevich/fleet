"""FR-24 / FR-25 / FR-26: runtime.toml reloads atomically; in-flight not killed."""
from __future__ import annotations

import asyncio
from pathlib import Path

from fleet.config import write_atomic
from fleet.schemas import Task

from tests.integration.conftest import (
    FakeClaudeCoder,
    MemoryQueue,
    fast_config,
    make_supervisor,
)


def _task(tid: str) -> Task:
    return Task(id=tid, title=f"slow-{tid}", description=None, status="open")


async def _wait_in_flight(sup, count: int, timeout: float = 10.0) -> None:
    """Wait until supervisor has `count` in-flight tasks."""
    deadline = asyncio.get_event_loop().time() + timeout
    while len(sup.in_flight) < count:
        await asyncio.sleep(0.1)
        if asyncio.get_event_loop().time() > deadline:
            raise TimeoutError(f"timed out waiting for {count} in-flight tasks")


def test_dynamic_config_max_concurrent_reloads(tmp_path: Path) -> None:
    """Writing max_concurrent=2 to TOML is picked up within config_poll_interval. (FR-25)"""
    queue = MemoryQueue()
    for i in range(4):
        queue.add_task(_task(f"t-{i:03d}"))

    coder = FakeClaudeCoder(scenario="slow", FAKE_CLAUDE_SLEEP_SEC="10")
    config = fast_config(max_concurrent=4)
    sup = make_supervisor(tmp_path, queue, coder=coder, config=config)

    async def _run() -> None:
        sup_task = asyncio.create_task(sup.run())
        try:
            # Wait for all 4 tasks to be claimed (4 poll cycles at 1s each)
            await _wait_in_flight(sup, 4, timeout=8.0)

            assert len(sup.in_flight) == 4, "expected 4 in-flight tasks before config change"
            in_flight_before = set(sup.in_flight.keys())

            # Write new max_concurrent=2 to the runtime.toml
            runtime_toml = tmp_path / ".fleet" / "runtime.toml"
            write_atomic(runtime_toml, {"max_concurrent": "2"})

            # Wait for config to be reloaded (1 poll interval + buffer)
            await asyncio.sleep(2.5)

            assert sup.config.max_concurrent == 2, (
                f"supervisor should have reloaded config; got {sup.config.max_concurrent}"
            )

            # FR-26: in-flight tasks must NOT be killed by config change
            still_in_flight = set(sup.in_flight.keys())
            assert still_in_flight == in_flight_before, (
                "no in-flight tasks should be killed on config change"
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


def test_dynamic_config_new_cap_respected_after_completion(tmp_path: Path) -> None:
    """After cap drop to 2, new spawns only happen when in_flight < 2. (FR-24)"""
    queue = MemoryQueue()
    # 4 tasks: first batch uses "slow", later claims use "clean_exit" via scenarios
    for i in range(4):
        queue.add_task(_task(f"t-{i:03d}"))
    # Add extra tasks that will be spawned post-cap
    for i in range(4, 6):
        queue.add_task(_task(f"t-{i:03d}"))

    # First 4 use slow (long sleep so they outlast the cap-change assertion); extras use clean_exit
    class ScenarioCyclingCoder(FakeClaudeCoder):
        def env(self, task: Task, task_dir: Path) -> dict[str, str]:
            base = super().env(task, task_dir)
            scenario = "slow" if int(task.id.split("-")[1]) < 4 else "clean_exit"
            base["FAKE_CLAUDE_SCENARIO"] = scenario
            base["FAKE_CLAUDE_SLEEP_SEC"] = "10"
            return base

    coder = ScenarioCyclingCoder()
    config = fast_config(max_concurrent=4)
    sup = make_supervisor(tmp_path, queue, coder=coder, config=config)

    async def _run() -> None:
        sup_task = asyncio.create_task(sup.run())
        try:
            await _wait_in_flight(sup, 4, timeout=8.0)

            runtime_toml = tmp_path / ".fleet" / "runtime.toml"
            write_atomic(runtime_toml, {"max_concurrent": "2"})

            # Wait for config reload
            await asyncio.sleep(2.0)
            assert sup.config.max_concurrent == 2

            # Still 4 in-flight (no kills) — slow tasks (10s) haven't completed yet
            assert len(sup.in_flight) == 4

            # Poll until ≥2 slow tasks complete and in_flight drops to the new cap.
            # Slow tasks were claimed ~1s apart and each sleeps 10s, so the second
            # completion lands ~11s after the first claim; 15s gives ample margin.
            deadline = asyncio.get_event_loop().time() + 15.0
            while len(sup.in_flight) > 2:
                await asyncio.sleep(0.2)
                if asyncio.get_event_loop().time() > deadline:
                    raise TimeoutError(
                        f"timed out waiting for in_flight <= 2; got {len(sup.in_flight)}"
                    )

            # Stable window: allow any (unwanted) new claims to surface.
            # claim_poll_interval is 1s, so 2s covers ≥1 poll cycle.
            await asyncio.sleep(2.0)

            # Cap enforced: no new spawns while in_flight >= cap.
            assert len(sup.in_flight) <= 2, (
                f"in_flight should remain <=2 after cap enforced; got {len(sup.in_flight)}"
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


