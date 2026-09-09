"""Tests for supervisor shutdown grace (unit under test: orchestrator/supervisor.py shutdown)."""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path

from fleet.core.config import RuntimeConfig
from fleet.core.task import Task, TaskOutcome, TaskOutcomeRecord
from fleet.orchestrator.supervisor import Supervisor
from tests.conftest import make_running_worker, make_supervisor

# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class StubQueue:
    def __init__(self) -> None:
        self.released: list[tuple[str, str]] = []

    def claim_next(self, claimer_id):
        return None

    def release(self, task_id, reason="", wait_sec=0):
        self.released.append((task_id, reason))

    def set_blocked(self, task_id, reason):
        pass

    def close(self, task_id, reason="completed"):
        pass

    def comment(self, task_id, body):
        pass

    def get(self, task_id):
        return Task(id=task_id, title="T", description=None, status="in_progress")

    def list_ready(self, limit=50):
        return []


def _make_supervisor(
    tmp_path: Path,
    queue: StubQueue,
    config: RuntimeConfig | None = None,
    shutdown_grace_sec: float | None = None,
) -> Supervisor:
    return make_supervisor(  # type: ignore[arg-type]
        tmp_path,
        queue=queue,
        config=config,
        services=[],
        checks=[],
        shutdown_grace_sec=shutdown_grace_sec,
    )


class _FakeRun:
    """Stand-in for WorkerRun: shutdown cancel is a no-op."""

    async def cancel(self) -> None:
        return None


def _track(s: Supervisor, task_id: str, t: asyncio.Task) -> None:
    s.state.running[task_id] = make_running_worker(
        task_id,
        None,
        task=Task(id=task_id, title="T", description=None, status="in_progress"),
        run=_FakeRun(),
        future=t,
    )


# ---------------------------------------------------------------------------
# SIGINT in-flight: all tasks released within grace
# ---------------------------------------------------------------------------


def test_shutdown_completes_quick_tasks_within_grace(tmp_path: Path) -> None:
    """Tasks that complete quickly are not force-released."""
    queue = StubQueue()

    async def _run() -> None:
        s = _make_supervisor(tmp_path, queue, shutdown_grace_sec=2)

        async def quick_task() -> TaskOutcomeRecord:
            # Short but nonzero: the task must still be in-flight at shutdown
            # so the test exercises completion *within* the grace window.
            await asyncio.sleep(0.05)
            return TaskOutcomeRecord(outcome=TaskOutcome.SUCCESS)

        task_id = "t-001"
        t = asyncio.create_task(quick_task())
        _track(s, task_id, t)

        await s._shutdown()

        # Task completed within grace → no force-release
        forced = [r for r in queue.released if "forced" in r[1]]
        assert len(forced) == 0

        # Cleanup
        if not t.done():
            t.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await t

    asyncio.run(_run())


def test_shutdown_before_run_still_unblocks_run(tmp_path: Path) -> None:
    """_shutdown() works before run(): the done event is created lazily."""
    queue = StubQueue()

    async def _run() -> None:
        s = _make_supervisor(tmp_path, queue)
        await s._shutdown()  # never ran run(): must not raise
        assert s.state.shutting_down
        rc = await asyncio.wait_for(s.run(), timeout=5.0)
        assert rc == 0

    asyncio.run(_run())


def test_shutdown_sets_shutting_down_flag(tmp_path: Path) -> None:
    """_shutdown sets state.shutting_down = True."""
    queue = StubQueue()

    async def _run() -> None:
        s = _make_supervisor(tmp_path, queue)
        assert not s.state.shutting_down
        await s._shutdown()
        assert s.state.shutting_down

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# SIGINT past grace with stubborn runner: forced release
# ---------------------------------------------------------------------------


def test_shutdown_force_releases_tasks_past_grace(tmp_path: Path) -> None:
    """Tasks that outlive the grace window are force-released via queue.release."""
    queue = StubQueue()

    async def _run() -> None:
        s = _make_supervisor(tmp_path, queue, shutdown_grace_sec=1)

        async def stubborn_task() -> TaskOutcomeRecord:
            await asyncio.Event().wait()  # block until cancelled; no fixed sleep
            return TaskOutcomeRecord(outcome=TaskOutcome.SUCCESS)

        task_id = "t-001"
        t = asyncio.create_task(stubborn_task())
        _track(s, task_id, t)

        await s._shutdown()

        forced = [r for r in queue.released if "forced" in r[1]]
        assert len(forced) == 1
        assert forced[0][0] == task_id

        # Cleanup
        t.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await t

    asyncio.run(_run())


def test_shutdown_force_releases_correct_task_id(tmp_path: Path) -> None:
    """Force-released reason contains 'supervisor shutdown'."""
    queue = StubQueue()

    async def _run() -> None:
        s = _make_supervisor(tmp_path, queue, shutdown_grace_sec=1)

        async def stubborn() -> TaskOutcomeRecord:
            await asyncio.Event().wait()  # block until cancelled; no fixed sleep
            return TaskOutcomeRecord(outcome=TaskOutcome.SUCCESS)

        task_id = "t-abc"
        t = asyncio.create_task(stubborn())
        _track(s, task_id, t)

        await s._shutdown()

        assert queue.released[0][0] == task_id
        assert "supervisor shutdown" in queue.released[0][1]

        t.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await t

    asyncio.run(_run())


def test_shutdown_idempotent(tmp_path: Path) -> None:
    """Calling _shutdown twice does not double-release or error."""
    queue = StubQueue()

    async def _run() -> None:
        s = _make_supervisor(tmp_path, queue, shutdown_grace_sec=1)

        async def stubborn() -> TaskOutcomeRecord:
            await asyncio.Event().wait()  # block until cancelled; no fixed sleep
            return TaskOutcomeRecord(outcome=TaskOutcome.SUCCESS)

        task_id = "t-001"
        t = asyncio.create_task(stubborn())
        _track(s, task_id, t)

        await s._shutdown()
        await s._shutdown()  # second call is a no-op

        forced = [r for r in queue.released if "forced" in r[1]]
        assert len(forced) == 1  # only one force-release, not two

        t.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await t

    asyncio.run(_run())
