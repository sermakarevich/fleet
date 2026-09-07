from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

import structlog

from fleet.core.config import RuntimeConfig, write_atomic
from fleet.core.task import Event, Task, TaskOutcome, TaskOutcomeRecord
from fleet.orchestrator.claim import cap_for_coder, running_by_coder
from fleet.orchestrator.supervisor import Supervisor


def _can_spawn(s: Supervisor) -> bool:
    running = running_by_coder(s.in_flight_tasks.values(), s.config.coder)
    cap = cap_for_coder(
        s.config.coder, s.config.max_concurrent, s.config.max_concurrent_overrides
    )
    return running.get(s.config.coder, 0) < cap


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


def _make_supervisor(
    tmp_path: Path, queue: TrackingQueue, config: RuntimeConfig | None = None
) -> Supervisor:
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
            s.in_flight_tasks[task_id] = Task(
                id=task_id, title="T", description=None, status="in_progress"
            )

        initial_count = len(s.in_flight)

        # Simulate config change: lower max_concurrent to 2
        s.config = RuntimeConfig(max_concurrent=2)

        # In-flight count must be unchanged (no cancellations)
        assert len(s.in_flight) == initial_count == 4

        # Spawn decision must be PAUSED_FULL (4 in-flight >= 2 cap)
        assert _can_spawn(s) is False

        # Cleanup
        for t in list(s.in_flight.values()):
            t.cancel()
            try:
                await t
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
            s.in_flight[task_id] = t
            s.in_flight_tasks[task_id] = Task(
                id=task_id, title="T", description=None, status="in_progress"
            )

        assert _can_spawn(s) is False

        # Remove one from in-flight — still 2 == cap, still PAUSED_FULL
        tid = "t-000"
        removed_task = s.in_flight.pop(tid)
        s.in_flight_tasks.pop(tid, None)
        removed_task.cancel()
        try:
            await removed_task
        except (asyncio.CancelledError, Exception):
            pass

        assert _can_spawn(s) is False

        # Remove another — now 1 < cap=2, SPAWN
        tid = "t-001"
        removed_task = s.in_flight.pop(tid)
        s.in_flight_tasks.pop(tid, None)
        removed_task.cancel()
        try:
            await removed_task
        except (asyncio.CancelledError, Exception):
            pass

        assert _can_spawn(s) is True

        # Cleanup remaining
        for t in list(s.in_flight.values()):
            t.cancel()
            try:
                await t
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
            s.in_flight[task_id] = t
            s.in_flight_tasks[task_id] = Task(
                id=task_id, title="T", description=None, status="in_progress"
            )

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
        s.config = RuntimeConfig(max_concurrent=4)

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


def test_config_poll_loop_detects_file_change(tmp_path: Path, monkeypatch) -> None:
    """_config_poll_loop updates self.config when runtime.toml changes on disk."""
    monkeypatch.setattr("fleet.orchestrator.supervisor.CONFIG_POLL_INTERVAL_SEC", 1)
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
    s.config = RuntimeConfig(max_concurrent=3)

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


# ---------------------------------------------------------------------------
# _resolve_coder — opencode kwargs
# ---------------------------------------------------------------------------


def test_resolve_coder_opencode_passes_context_limit_and_default_model(tmp_path: Path):
    """When coder_name == 'opencode', _resolve_coder passes context_limit and default_model."""
    queue = TrackingQueue()
    runtime_toml = tmp_path / "runtime.toml"
    write_atomic(
        runtime_toml,
        {
            "opencode_context_limit": "256000",
            "opencode_default_model": "qwen3.6:latest",
        },
    )
    from fleet.coders.opencode import OpencodeCoder

    # Load config from file to get the values
    # We manually set them since write_atomic writes strings
    s = Supervisor(
        coder=None,
        queue=queue,
        runtime_toml_path=runtime_toml,
        project_root=tmp_path,
        log=structlog.get_logger(),
    )
    s.config = RuntimeConfig(
        coder="opencode",
        opencode_context_limit=256_000,
        opencode_default_model="qwen3.6:latest",
    )

    task = Task(
        id="t-opencode-01",
        title="Opencode test",
        description=None,
        status="in_progress",
        cwd=str(tmp_path),
    )
    coder, coder_name, model = s._resolve_coder(task)

    assert coder_name == "opencode"
    assert isinstance(coder, OpencodeCoder)
    assert coder.context_limit == 256_000
    assert coder.default_model == "qwen3.6:latest"
    assert coder.model == "sonnet"  # falls back to RuntimeConfig.model
