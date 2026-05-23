from __future__ import annotations

import asyncio
from pathlib import Path

import structlog

from fleet.schemas import RuntimeConfig, Task, TaskOutcome, TaskOutcomeRecord
from fleet.supervisor import Supervisor


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class StubCoder:
    name = "stub"

    def build_argv(self, task, artifact_dir):
        return ["echo"]

    def env(self, task, artifact_dir):
        return {}

    def normalize_event(self, raw_line):
        return None


class StubQueue:
    def __init__(self) -> None:
        self.released: list[tuple[str, str]] = []

    def claim_next(self, claimer_id):
        return None

    def release(self, task_id, reason=""):
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


def _make_supervisor(tmp_path: Path, queue: StubQueue, config: RuntimeConfig | None = None) -> Supervisor:
    s = Supervisor(
        coder=StubCoder(),
        queue=queue,
        runtime_toml_path=tmp_path / "runtime.toml",
        project_root=tmp_path,
        log=structlog.get_logger(),
    )
    if config is not None:
        s.config = config
    s._done = asyncio.Event()  # pre-init so _shutdown can set it
    return s


# ---------------------------------------------------------------------------
# SIGINT in-flight: all tasks released within grace
# ---------------------------------------------------------------------------


def test_shutdown_completes_quick_tasks_within_grace(tmp_path: Path) -> None:
    """Tasks that complete quickly are not force-released."""
    queue = StubQueue()

    async def _run() -> None:
        s = _make_supervisor(tmp_path, queue, config=RuntimeConfig(shutdown_grace_sec=2))
        s._done = asyncio.Event()

        async def quick_task() -> TaskOutcomeRecord:
            await asyncio.sleep(0.05)
            return TaskOutcomeRecord(outcome=TaskOutcome.SUCCESS)

        task_id = "t-001"
        t = asyncio.create_task(quick_task())
        s.in_flight[task_id] = t
        s.in_flight_tasks[task_id] = Task(id=task_id, title="T", description=None, status="in_progress")

        await s._shutdown()

        # Task completed within grace → no force-release
        forced = [r for r in queue.released if "forced" in r[1]]
        assert len(forced) == 0

        # Cleanup
        if not t.done():
            t.cancel()
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass

    asyncio.run(_run())


def test_shutdown_no_in_flight_sets_done(tmp_path: Path) -> None:
    """Shutdown with no in-flight tasks completes and sets _done."""
    queue = StubQueue()

    async def _run() -> None:
        s = _make_supervisor(tmp_path, queue, config=RuntimeConfig(shutdown_grace_sec=1))
        s._done = asyncio.Event()
        await s._shutdown()
        assert s._done.is_set()

    asyncio.run(_run())


def test_shutdown_sets_shutting_down_flag(tmp_path: Path) -> None:
    """_shutdown sets _shutting_down = True."""
    queue = StubQueue()

    async def _run() -> None:
        s = _make_supervisor(tmp_path, queue)
        s._done = asyncio.Event()
        assert not s._shutting_down
        await s._shutdown()
        assert s._shutting_down

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# SIGINT past grace with stubborn runner: forced release
# ---------------------------------------------------------------------------


def test_shutdown_force_releases_tasks_past_grace(tmp_path: Path) -> None:
    """Tasks that outlive the grace window are force-released via queue.release."""
    queue = StubQueue()

    async def _run() -> None:
        s = _make_supervisor(tmp_path, queue, config=RuntimeConfig(shutdown_grace_sec=1))
        s._done = asyncio.Event()

        async def stubborn_task() -> TaskOutcomeRecord:
            await asyncio.sleep(9999)
            return TaskOutcomeRecord(outcome=TaskOutcome.SUCCESS)

        task_id = "t-001"
        t = asyncio.create_task(stubborn_task())
        s.in_flight[task_id] = t
        s.in_flight_tasks[task_id] = Task(id=task_id, title="T", description=None, status="in_progress")

        await s._shutdown()

        forced = [r for r in queue.released if "forced" in r[1]]
        assert len(forced) == 1
        assert forced[0][0] == task_id

        # Cleanup
        t.cancel()
        try:
            await t
        except (asyncio.CancelledError, Exception):
            pass

    asyncio.run(_run())


def test_shutdown_force_releases_correct_task_id(tmp_path: Path) -> None:
    """Force-released reason contains 'supervisor shutdown'."""
    queue = StubQueue()

    async def _run() -> None:
        s = _make_supervisor(tmp_path, queue, config=RuntimeConfig(shutdown_grace_sec=1))
        s._done = asyncio.Event()

        async def stubborn() -> TaskOutcomeRecord:
            await asyncio.sleep(9999)
            return TaskOutcomeRecord(outcome=TaskOutcome.SUCCESS)

        task_id = "t-abc"
        t = asyncio.create_task(stubborn())
        s.in_flight[task_id] = t
        s.in_flight_tasks[task_id] = Task(id=task_id, title="T", description=None, status="in_progress")

        await s._shutdown()

        assert queue.released[0][0] == task_id
        assert "supervisor shutdown" in queue.released[0][1]

        t.cancel()
        try:
            await t
        except (asyncio.CancelledError, Exception):
            pass

    asyncio.run(_run())


def test_shutdown_idempotent(tmp_path: Path) -> None:
    """Calling _shutdown twice does not double-release or error."""
    queue = StubQueue()

    async def _run() -> None:
        s = _make_supervisor(tmp_path, queue, config=RuntimeConfig(shutdown_grace_sec=1))
        s._done = asyncio.Event()

        async def stubborn() -> TaskOutcomeRecord:
            await asyncio.sleep(9999)
            return TaskOutcomeRecord(outcome=TaskOutcome.SUCCESS)

        task_id = "t-001"
        t = asyncio.create_task(stubborn())
        s.in_flight[task_id] = t
        s.in_flight_tasks[task_id] = Task(id=task_id, title="T", description=None, status="in_progress")

        await s._shutdown()
        await s._shutdown()  # second call is a no-op

        forced = [r for r in queue.released if "forced" in r[1]]
        assert len(forced) == 1  # only one force-release, not two

        t.cancel()
        try:
            await t
        except (asyncio.CancelledError, Exception):
            pass

    asyncio.run(_run())
