from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

import structlog

from fleet.config import write_atomic
from fleet.schemas import Event, RuntimeConfig, Task, TaskOutcome, TaskOutcomeRecord
from fleet.supervisor import Supervisor
from fleet.supervisor_spawn import SpawnDecision


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


class TrackingQueue:
    def __init__(self, status: str = "in_progress") -> None:
        self._status = status
        self.released: list[tuple[str, str]] = []
        self.blocked: list[tuple[str, str]] = []
        self.comments: list[tuple[str, str]] = []

    def claim_next(self, claimer_id):
        return None

    def release(self, task_id, reason=""):
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


def _make_supervisor(tmp_path: Path, queue: TrackingQueue, config: RuntimeConfig | None = None) -> Supervisor:
    s = Supervisor(
        coder=StubCoder(),
        queue=queue,
        runtime_toml_path=tmp_path / "runtime.toml",
        project_root=tmp_path,
        log=structlog.get_logger(),
    )
    if config is not None:
        s.config = config
    return s


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
            s.in_flight[task_id] = t
            s.in_flight_tasks[task_id] = Task(id=task_id, title="T", description=None, status="in_progress")

        initial_count = len(s.in_flight)

        # Simulate config change: lower max_concurrent to 2
        s.config = RuntimeConfig(max_concurrent=2)

        # In-flight count must be unchanged (no cancellations)
        assert len(s.in_flight) == initial_count == 4

        # Spawn decision must be PAUSED_FULL (4 in-flight >= 2 cap)
        decision = s.spawn_controller.decide(
            in_flight=len(s.in_flight),
            max_concurrent=s.config.max_concurrent,
            threshold_pct=float(s.config.rate_limit_threshold_pct),
            gauge=s.rate_gauge,
        )
        assert decision == SpawnDecision.PAUSED_FULL

        # Cleanup
        for t in list(s.in_flight.values()):
            t.cancel()
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass

    asyncio.run(_run())


def test_lowered_max_concurrent_new_spawns_blocked_until_count_drops(tmp_path: Path) -> None:
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
            s.in_flight[task_id] = t
            s.in_flight_tasks[task_id] = Task(id=task_id, title="T", description=None, status="in_progress")

        decision = s.spawn_controller.decide(
            in_flight=len(s.in_flight),
            max_concurrent=s.config.max_concurrent,
            threshold_pct=float(s.config.rate_limit_threshold_pct),
            gauge=s.rate_gauge,
        )
        assert decision == SpawnDecision.PAUSED_FULL

        # Remove one from in-flight — still 2 == cap, still PAUSED_FULL
        tid = "t-000"
        removed_task = s.in_flight.pop(tid)
        s.in_flight_tasks.pop(tid, None)
        removed_task.cancel()
        try:
            await removed_task
        except (asyncio.CancelledError, Exception):
            pass

        decision = s.spawn_controller.decide(
            in_flight=len(s.in_flight),
            max_concurrent=s.config.max_concurrent,
            threshold_pct=float(s.config.rate_limit_threshold_pct),
            gauge=s.rate_gauge,
        )
        assert decision == SpawnDecision.PAUSED_FULL

        # Remove another — now 1 < cap=2, SPAWN
        tid = "t-001"
        removed_task = s.in_flight.pop(tid)
        s.in_flight_tasks.pop(tid, None)
        removed_task.cancel()
        try:
            await removed_task
        except (asyncio.CancelledError, Exception):
            pass

        decision = s.spawn_controller.decide(
            in_flight=len(s.in_flight),
            max_concurrent=s.config.max_concurrent,
            threshold_pct=float(s.config.rate_limit_threshold_pct),
            gauge=s.rate_gauge,
        )
        assert decision == SpawnDecision.SPAWN

        # Cleanup remaining
        for t in list(s.in_flight.values()):
            t.cancel()
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# Lowering rate_limit_threshold_pct while above new threshold: pauses spawns
# ---------------------------------------------------------------------------


def test_lowered_rate_threshold_blocks_spawning(tmp_path: Path) -> None:
    """After lowering threshold while gauge > new threshold, controller pauses."""
    queue = TrackingQueue()
    s = _make_supervisor(tmp_path, queue)
    s.config = RuntimeConfig(max_concurrent=4, rate_limit_threshold_pct=90)

    # Set gauge to 85% (below old threshold of 90 → SPAWN)
    s.rate_gauge.update(
        Event(
            kind="rate_limit_info",
            raw={},
            ts=datetime.now(tz=timezone.utc),
            rate_info={"usage_pct": 85.0},
        )
    )

    decision = s.spawn_controller.decide(
        in_flight=0,
        max_concurrent=4,
        threshold_pct=90.0,
        gauge=s.rate_gauge,
    )
    assert decision == SpawnDecision.SPAWN

    # Lower threshold to 80 — now 85% > 80% → PAUSED_RATE_LIMIT
    s.config = RuntimeConfig(max_concurrent=4, rate_limit_threshold_pct=80)

    decision = s.spawn_controller.decide(
        in_flight=0,
        max_concurrent=s.config.max_concurrent,
        threshold_pct=float(s.config.rate_limit_threshold_pct),
        gauge=s.rate_gauge,
    )
    assert decision == SpawnDecision.PAUSED_RATE_LIMIT


def test_lowered_rate_threshold_does_not_cancel_in_flight(tmp_path: Path) -> None:
    """Changing rate threshold while tasks are in-flight does not cancel them."""
    queue = TrackingQueue()
    s = _make_supervisor(tmp_path, queue)
    s.config = RuntimeConfig(max_concurrent=4, rate_limit_threshold_pct=90)

    async def _run() -> None:
        for i in range(3):
            task_id = f"t-{i:03d}"

            async def forever() -> TaskOutcomeRecord:
                await asyncio.sleep(999)
                return TaskOutcomeRecord(outcome=TaskOutcome.SUCCESS)

            t = asyncio.create_task(forever())
            s.in_flight[task_id] = t
            s.in_flight_tasks[task_id] = Task(id=task_id, title="T", description=None, status="in_progress")

        initial_count = len(s.in_flight)

        # Lower threshold below current gauge level
        s.rate_gauge.update(
            Event(
                kind="rate_limit_info",
                raw={},
                ts=datetime.now(tz=timezone.utc),
                rate_info={"usage_pct": 85.0},
            )
        )
        s.config = RuntimeConfig(max_concurrent=4, rate_limit_threshold_pct=80)

        # In-flight count unchanged
        assert len(s.in_flight) == initial_count == 3

        # Cleanup
        for t in list(s.in_flight.values()):
            t.cancel()
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# Updating retry_limit mid-flight: applied on the next failure
# ---------------------------------------------------------------------------


def test_updated_retry_limit_applies_on_next_failure(tmp_path: Path) -> None:
    """After changing retry_limit, the new value governs the next failure outcome."""
    queue = TrackingQueue()
    s = _make_supervisor(tmp_path, queue)
    s.config = RuntimeConfig(retry_limit=5)  # high limit initially

    task = Task(id="t-001", title="Test", description=None, status="in_progress")
    failure = TaskOutcomeRecord(outcome=TaskOutcome.FAILURE, exit_code=1, reason="crash")

    # First failure — below limit (1 < 5) → release
    s._handle_outcome(task, failure)
    assert len(queue.released) == 1
    assert len(queue.blocked) == 0

    # Lower retry_limit to 1 — second failure (count=2 >= 1) → set_blocked
    s.config = RuntimeConfig(retry_limit=1)
    s._handle_outcome(task, failure)
    assert len(queue.blocked) == 1


def test_config_poll_loop_detects_file_change(tmp_path: Path) -> None:
    """_config_poll_loop updates self.config when runtime.toml changes on disk."""
    queue = TrackingQueue()
    toml_path = tmp_path / "runtime.toml"
    write_atomic(toml_path, {"max_concurrent": "3"})

    s = Supervisor(
        coder=StubCoder(),
        queue=queue,
        runtime_toml_path=toml_path,
        project_root=tmp_path,
        log=structlog.get_logger(),
    )
    # Use short poll interval for the test
    s.config = RuntimeConfig(config_poll_interval_sec=1, max_concurrent=3)

    async def _run() -> None:
        s._done = asyncio.Event()
        poll_task = asyncio.create_task(s._config_poll_loop())

        # Give the loop one tick to start, then update the file
        await asyncio.sleep(0.05)
        write_atomic(toml_path, {"max_concurrent": "7"})

        # Wait for the poll interval to fire
        await asyncio.sleep(1.3)

        assert s.config.max_concurrent == 7

        poll_task.cancel()
        try:
            await poll_task
        except (asyncio.CancelledError, Exception):
            pass

    asyncio.run(_run())
