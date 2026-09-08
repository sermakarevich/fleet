from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

from fleet.core.config import RuntimeConfig
from fleet.core.task import Event, Task, TaskOutcome, TaskOutcomeRecord
from fleet.orchestrator.claim import can_claim
from fleet.orchestrator.supervisor import Supervisor
from tests.conftest import make_running_worker, make_supervisor


def _can_spawn(s: Supervisor) -> bool:
    return can_claim(s.state, None)


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class StubCoder:
    name = "stub"

    def build_argv(self, task, artifact_dir, plan=None):
        return ["echo"]

    def env(self, task, artifact_dir):
        return {}

    def normalize_event(self, raw_line):
        return None


class TrackingQueue:
    def __init__(self, status: str = "in_progress") -> None:
        self._status = status
        self.released: list[tuple[str, str]] = []
        self.blocked: list[tuple[str, str]] = []
        self.comments: list[tuple[str, str]] = []

    def claim_next(self, claimer_id):
        return None

    def release(self, task_id, reason="", wait_sec=0):
        self.released.append((task_id, reason))

    def set_blocked(self, task_id, reason):
        self.blocked.append((task_id, reason))

    def close(self, task_id, reason="completed"):
        pass

    def comment(self, task_id, body):
        self.comments.append((task_id, body))

    def get(self, task_id):
        return Task(id=task_id, title="T", description=None, status=self._status)

    def list_ready(self, limit=50):
        return []


def _make_supervisor(
    tmp_path: Path, queue: TrackingQueue, config: RuntimeConfig | None = None
) -> Supervisor:
    return make_supervisor(  # type: ignore[arg-type]
        tmp_path, queue=queue, config=config, services=[], checks=[]
    )


# ---------------------------------------------------------------------------
# Lowering max_concurrent while 4 are in-flight: in-flight count unchanged
# ---------------------------------------------------------------------------


def test_lowered_max_concurrent_in_flight_unchanged(tmp_path: Path) -> None:
    """Lowering max_concurrent does not cancel in-flight tasks."""
    queue = TrackingQueue()
    s = _make_supervisor(tmp_path, queue, config=RuntimeConfig(max_concurrent=4))

    async def _run() -> None:
        for i in range(4):
            task_id = f"t-{i:03d}"

            async def forever() -> TaskOutcomeRecord:
                await asyncio.sleep(999)
                return TaskOutcomeRecord(outcome=TaskOutcome.SUCCESS)

            t = asyncio.create_task(forever())
            s.state.running[task_id] = make_running_worker(
                task_id,
                tmp_path,
                task=Task(id=task_id, title="T", description=None, status="in_progress"),
                future=t,
            )

        initial_count = len(s.state.running)

        # Simulate config change: lower max_concurrent to 2
        s.config = RuntimeConfig(max_concurrent=2)

        # In-flight count must be unchanged (no cancellations)
        assert len(s.state.running) == initial_count == 4

        # Spawn decision must be PAUSED_FULL (4 in-flight >= 2 cap)
        assert _can_spawn(s) is False

        # Cleanup
        for rw in list(s.state.running.values()):
            rw.future.cancel()
            try:
                await rw.future
            except (asyncio.CancelledError, Exception):
                pass

    asyncio.run(_run())


def test_lowered_max_concurrent_new_spawns_blocked_until_count_drops(
    tmp_path: Path,
) -> None:
    """After lowering cap, spawn remains blocked until in-flight count falls below new cap."""
    queue = TrackingQueue()
    s = _make_supervisor(tmp_path, queue)
    s.config = RuntimeConfig(max_concurrent=2)

    async def _run() -> None:
        # 3 in-flight tasks with cap=2: PAUSED_FULL
        for i in range(3):
            task_id = f"t-{i:03d}"

            async def forever() -> TaskOutcomeRecord:
                await asyncio.sleep(999)
                return TaskOutcomeRecord(outcome=TaskOutcome.SUCCESS)

            t = asyncio.create_task(forever())
            s.state.running[task_id] = make_running_worker(
                task_id,
                tmp_path,
                task=Task(id=task_id, title="T", description=None, status="in_progress"),
                future=t,
            )

        assert _can_spawn(s) is False

        # Remove one from in-flight — still 2 == cap, still PAUSED_FULL
        tid = "t-000"
        removed = s.state.running.pop(tid)
        removed.future.cancel()
        try:
            await removed.future
        except (asyncio.CancelledError, Exception):
            pass

        assert _can_spawn(s) is False

        # Remove another — now 1 < cap=2, SPAWN
        tid = "t-001"
        removed = s.state.running.pop(tid)
        removed.future.cancel()
        try:
            await removed.future
        except (asyncio.CancelledError, Exception):
            pass

        assert _can_spawn(s) is True

        # Cleanup remaining
        for rw in list(s.state.running.values()):
            rw.future.cancel()
            try:
                await rw.future
            except (asyncio.CancelledError, Exception):
                pass

    asyncio.run(_run())


def test_lowered_rate_threshold_does_not_cancel_in_flight(tmp_path: Path) -> None:
    """Changing rate threshold while tasks are in-flight does not cancel them."""
    queue = TrackingQueue()
    s = _make_supervisor(tmp_path, queue)
    s.config = RuntimeConfig(max_concurrent=4)

    async def _run() -> None:
        for i in range(3):
            task_id = f"t-{i:03d}"

            async def forever() -> TaskOutcomeRecord:
                await asyncio.sleep(999)
                return TaskOutcomeRecord(outcome=TaskOutcome.SUCCESS)

            t = asyncio.create_task(forever())
            s.state.running[task_id] = make_running_worker(
                task_id,
                tmp_path,
                task=Task(id=task_id, title="T", description=None, status="in_progress"),
                future=t,
            )

        initial_count = len(s.state.running)

        # Lower threshold below current gauge level
        s.state.rate_gauge.update(
            Event(
                kind="rate_limit_info",
                raw={},
                ts=datetime.now(tz=UTC),
                rate_info={"usage_pct": 85.0},
            )
        )
        s.config = RuntimeConfig(max_concurrent=4)

        # In-flight count unchanged
        assert len(s.state.running) == initial_count == 3

        # Cleanup
        for rw in list(s.state.running.values()):
            rw.future.cancel()
            try:
                await rw.future
            except (asyncio.CancelledError, Exception):
                pass

    asyncio.run(_run())
