"""FR-06: Graceful shutdown releases all tasks; stubborn child gets SIGKILL."""
from __future__ import annotations

import asyncio
import subprocess
import sys
import time
from pathlib import Path

from fleet.schemas import Task

from tests.integration.conftest import (
    FakeClaudeCoder,
    MemoryQueue,
    fast_config,
    make_supervisor,
)

_FAKE_CLAUDE_NAME = "fake_claude.py"


def _no_orphans(tag: str, timeout: float = 2.0) -> bool:
    """Return True if no `fake_claude.py` processes scoped to `tag` survive.

    `tag` should be a string unique to the current test (typically `str(tmp_path)`).
    It is matched against the subprocess command line — `FakeClaudeCoder`
    embeds `artifact_dir` (which is rooted under `tmp_path`) in the prompt argv,
    so this filter reliably distinguishes one test's children from another's.

    A short poll loop tolerates the brief window where a SIGTERM'd child has
    exited but the kernel has not yet finished reaping it.
    """
    pattern = f"{_FAKE_CLAUDE_NAME}.*{tag}"
    deadline = time.monotonic() + timeout
    while True:
        result = subprocess.run(
            ["pgrep", "-f", pattern],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:  # pgrep exits 1 when no match
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.05)


def _task(tid: str) -> Task:
    return Task(id=tid, title=f"slow-{tid}", description=None, status="open")


async def _wait_in_flight(sup, count: int, timeout: float = 10.0) -> None:
    deadline = asyncio.get_event_loop().time() + timeout
    while len(sup.in_flight) < count:
        await asyncio.sleep(0.1)
        if asyncio.get_event_loop().time() > deadline:
            raise TimeoutError(f"timed out waiting for {count} in-flight tasks")


def test_shutdown_releases_all_tasks(tmp_path: Path) -> None:
    """All 3 in-flight tasks are released to open after SIGINT. (FR-06)"""
    queue = MemoryQueue()
    for i in range(3):
        queue.add_task(_task(f"t-{i:03d}"))

    coder = FakeClaudeCoder(scenario="slow", FAKE_CLAUDE_SLEEP_SEC="10")
    config = fast_config(
        max_concurrent=3,
        claim_poll_interval_sec=1,
        shutdown_grace_sec=3,
    )
    sup = make_supervisor(tmp_path, queue, coder=coder, config=config)

    async def _run() -> None:
        sup_task = asyncio.create_task(sup.run())
        try:
            await _wait_in_flight(sup, 3, timeout=8.0)
            assert len(sup.in_flight) == 3

            await sup._shutdown()
            await asyncio.wait_for(sup_task, timeout=8.0)

        except asyncio.TimeoutError:
            sup_task.cancel()
            try:
                await sup_task
            except (asyncio.CancelledError, Exception):
                pass

    asyncio.run(_run())

    # All 3 tasks should be released (either gracefully or force-released)
    released_ids = {tid for tid, _ in queue.released}
    assert released_ids == {"t-000", "t-001", "t-002"}, (
        f"all tasks should be released; got {released_ids}"
    )

    # No orphan subprocesses (scoped to this test's tmp_path to avoid
    # cross-test contamination within the same pytest run).
    assert _no_orphans(str(tmp_path)), (
        "no fake_claude.py processes should remain after shutdown"
    )


def test_shutdown_all_tasks_back_to_open(tmp_path: Path) -> None:
    """After shutdown, all task statuses are 'open' (re-queueable). (FR-06)"""
    queue = MemoryQueue()
    for i in range(3):
        queue.add_task(_task(f"t-{i:03d}"))

    coder = FakeClaudeCoder(scenario="slow", FAKE_CLAUDE_SLEEP_SEC="10")
    config = fast_config(max_concurrent=3, claim_poll_interval_sec=1, shutdown_grace_sec=3)
    sup = make_supervisor(tmp_path, queue, coder=coder, config=config)

    async def _run() -> None:
        sup_task = asyncio.create_task(sup.run())
        try:
            await _wait_in_flight(sup, 3, timeout=8.0)
            await sup._shutdown()
            await asyncio.wait_for(sup_task, timeout=8.0)
        except asyncio.TimeoutError:
            sup_task.cancel()
            try:
                await sup_task
            except (asyncio.CancelledError, Exception):
                pass

    asyncio.run(_run())

    for tid in ("t-000", "t-001", "t-002"):
        status = queue._tasks[tid].status
        assert status == "open", f"task {tid} should be open after shutdown; got {status}"


def test_shutdown_stubborn_child_gets_sigkill(tmp_path: Path) -> None:
    """Subprocess ignoring SIGTERM is SIGKILL'd after grace; task still released. (FR-06)"""
    queue = MemoryQueue()
    # 2 normal slow tasks + 1 stubborn (ignores SIGTERM)
    for i in range(2):
        queue.add_task(_task(f"t-{i:03d}"))
    queue.add_task(_task("t-stubborn"))

    class MixedCoder(FakeClaudeCoder):
        def env(self, task: Task, task_dir: Path) -> dict[str, str]:
            base = super().env(task, task_dir)
            if task.id == "t-stubborn":
                base["FAKE_CLAUDE_SCENARIO"] = "slow_ignore_sigterm"
            else:
                base["FAKE_CLAUDE_SCENARIO"] = "slow"
            base["FAKE_CLAUDE_SLEEP_SEC"] = "30"
            return base

    coder = MixedCoder()
    config = fast_config(
        max_concurrent=3,
        claim_poll_interval_sec=1,
        shutdown_grace_sec=2,  # short grace so SIGKILL fires quickly
    )
    sup = make_supervisor(tmp_path, queue, coder=coder, config=config)

    async def _run() -> None:
        sup_task = asyncio.create_task(sup.run())
        try:
            await _wait_in_flight(sup, 3, timeout=8.0)
            await sup._shutdown()
            # Allow enough time: grace (2s) + SIGKILL wait + cleanup
            await asyncio.wait_for(sup_task, timeout=10.0)
        except asyncio.TimeoutError:
            sup_task.cancel()
            try:
                await sup_task
            except (asyncio.CancelledError, Exception):
                pass

    asyncio.run(_run())

    released_ids = {tid for tid, _ in queue.released}
    assert "t-stubborn" in released_ids, (
        "stubborn task should be released after SIGKILL"
    )
    assert _no_orphans(str(tmp_path)), (
        "no fake_claude.py processes should survive shutdown"
    )


def test_shutdown_exit_code_zero(tmp_path: Path) -> None:
    """supervisor.run() returns 0 after graceful shutdown."""
    queue = MemoryQueue()
    queue.add_task(_task("t-000"))

    coder = FakeClaudeCoder(scenario="slow", FAKE_CLAUDE_SLEEP_SEC="10")
    config = fast_config(max_concurrent=1, claim_poll_interval_sec=1, shutdown_grace_sec=2)
    sup = make_supervisor(tmp_path, queue, coder=coder, config=config)

    async def _run() -> int:
        sup_task = asyncio.create_task(sup.run())
        await _wait_in_flight(sup, 1, timeout=5.0)
        await sup._shutdown()
        try:
            rc = await asyncio.wait_for(sup_task, timeout=8.0)
        except asyncio.TimeoutError:
            sup_task.cancel()
            rc = -1
        return rc

    rc = asyncio.run(_run())
    assert rc == 0
