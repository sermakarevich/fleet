"""Integration tests for the manual task kill mechanism."""
from __future__ import annotations

import asyncio
import subprocess
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
    pattern = f"{_FAKE_CLAUDE_NAME}.*{tag}"
    deadline = time.monotonic() + timeout
    while True:
        result = subprocess.run(
            ["pgrep", "-f", pattern],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.05)


def _task(tid: str) -> Task:
    return Task(id=tid, title=f"kill-{tid}", description=None, status="open")


async def _wait_in_flight(sup, count: int, timeout: float = 10.0) -> None:
    deadline = asyncio.get_event_loop().time() + timeout
    while len(sup.in_flight) < count:
        await asyncio.sleep(0.1)
        if asyncio.get_event_loop().time() > deadline:
            raise TimeoutError(f"timed out waiting for {count} in-flight tasks")


def test_kill_blocks_task_with_comment(tmp_path: Path) -> None:
    """Killing a running task moves it to blocked and adds a comment."""
    queue = MemoryQueue()
    queue.add_task(_task("t-001"))

    coder = FakeClaudeCoder(scenario="slow", FAKE_CLAUDE_SLEEP_SEC="30")
    config = fast_config(max_concurrent=1)
    sup = make_supervisor(tmp_path, queue, coder=coder, config=config)

    done = asyncio.Event()

    def on_event(method: str, task_id: str) -> None:
        if method == "set_blocked" and task_id == "t-001":
            done.set()

    queue.add_listener(on_event)

    task_dir = tmp_path / "tasks" / "t-001"

    async def _run() -> None:
        sup_task = asyncio.create_task(sup.run())
        try:
            await _wait_in_flight(sup, 1, timeout=8.0)
            # Write the kill sentinel
            task_dir.mkdir(parents=True, exist_ok=True)
            (task_dir / ".kill").touch()
            # Wait for supervisor to process the kill and block the task
            await asyncio.wait_for(done.wait(), timeout=8.0)
        finally:
            await sup._shutdown()
            try:
                await asyncio.wait_for(sup_task, timeout=5.0)
            except (asyncio.TimeoutError, asyncio.CancelledError, Exception):
                sup_task.cancel()
                try:
                    await sup_task
                except (asyncio.CancelledError, Exception):
                    pass

    asyncio.run(_run())

    assert queue._tasks["t-001"].status == "blocked", (
        f"task should be blocked after kill; got {queue._tasks['t-001'].status}"
    )
    assert len(queue.blocked) >= 1
    assert any(tid == "t-001" for tid, _ in queue.blocked)
    assert any(
        "t-001" == tid and "manual" in body.lower()
        for tid, body in queue.comments
    ), f"expected a 'manual interruption' comment; got {queue.comments}"
    assert _no_orphans(str(tmp_path)), "no fake_claude.py processes should survive kill"


def test_kill_sentinel_removed_after_processing(tmp_path: Path) -> None:
    """The .kill sentinel file is removed once the supervisor processes it."""
    queue = MemoryQueue()
    queue.add_task(_task("t-002"))

    coder = FakeClaudeCoder(scenario="slow", FAKE_CLAUDE_SLEEP_SEC="30")
    config = fast_config(max_concurrent=1)
    sup = make_supervisor(tmp_path, queue, coder=coder, config=config)

    done = asyncio.Event()

    def on_event(method: str, task_id: str) -> None:
        if method == "set_blocked" and task_id == "t-002":
            done.set()

    queue.add_listener(on_event)

    task_dir = tmp_path / "tasks" / "t-002"
    kill_file = task_dir / ".kill"

    async def _run() -> None:
        sup_task = asyncio.create_task(sup.run())
        try:
            await _wait_in_flight(sup, 1, timeout=8.0)
            task_dir.mkdir(parents=True, exist_ok=True)
            kill_file.touch()
            await asyncio.wait_for(done.wait(), timeout=8.0)
        finally:
            await sup._shutdown()
            try:
                await asyncio.wait_for(sup_task, timeout=5.0)
            except (asyncio.TimeoutError, asyncio.CancelledError, Exception):
                sup_task.cancel()
                try:
                    await sup_task
                except (asyncio.CancelledError, Exception):
                    pass

    asyncio.run(_run())

    assert not kill_file.exists(), ".kill sentinel should be removed after processing"


def test_stale_kill_sentinel_ignored_on_fresh_run(tmp_path: Path) -> None:
    """A pre-existing .kill sentinel must not kill a freshly spawned run."""
    queue = MemoryQueue()
    queue.add_task(_task("t-003"))

    # Plant the sentinel before the task is ever claimed or spawned.
    task_dir = tmp_path / "tasks" / "t-003"
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / ".kill").touch()

    coder = FakeClaudeCoder(scenario="clean_exit")
    config = fast_config(max_concurrent=1)
    sup = make_supervisor(tmp_path, queue, coder=coder, config=config)

    done = asyncio.Event()

    def on_event(method: str, task_id: str) -> None:
        # Fire on either completion path so the test doesn't need to time out.
        if method in ("release", "set_blocked") and task_id == "t-003":
            done.set()

    queue.add_listener(on_event)

    async def _run() -> None:
        sup_task = asyncio.create_task(sup.run())
        try:
            await asyncio.wait_for(done.wait(), timeout=15.0)
        except asyncio.TimeoutError:
            pass
        finally:
            await sup._shutdown()
            try:
                await asyncio.wait_for(sup_task, timeout=5.0)
            except (asyncio.TimeoutError, asyncio.CancelledError, Exception):
                sup_task.cancel()
                try:
                    await sup_task
                except (asyncio.CancelledError, Exception):
                    pass

    asyncio.run(_run())

    assert queue._tasks["t-003"].status != "blocked", (
        "stale .kill sentinel must not block a freshly spawned run"
    )
