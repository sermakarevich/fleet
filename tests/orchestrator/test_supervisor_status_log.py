from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import structlog

from fleet.core.config import RuntimeConfig
from fleet.core.task import Event, Task, TaskOutcome, TaskOutcomeRecord
from fleet.orchestrator.status_log import StatusLog, fleet_log_context
from fleet.orchestrator.supervisor import Supervisor
from fleet.state.journal import setup_supervisor_logger
from tests.helpers.task_dir import make_attempt

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


class StubQueue:
    def __init__(self, status: str = "in_progress") -> None:
        self._status = status

    def claim_next(self, claimer_id):
        return None

    def release(self, task_id, reason="", wait_sec=0):
        pass

    def set_blocked(self, task_id, reason):
        pass

    def close(self, task_id, reason="completed"):
        pass

    def comment(self, task_id, body):
        pass

    def get(self, task_id):
        return Task(id=task_id, title="T", description=None, status=self._status)

    def list_ready(self, limit=50):
        return []


def _make_supervisor(
    tmp_path: Path,
    log: structlog.BoundLogger | None = None,
    config: RuntimeConfig | None = None,
) -> Supervisor:
    s = Supervisor(
        coder=StubCoder(),
        queue=StubQueue(),
        runtime_toml_path=tmp_path / "runtime.toml",
        project_root=tmp_path,
        log=log or structlog.get_logger(),
    )
    if config is not None:
        s.config = config
    return s


def _read_fleet_log(log_root: Path) -> list[dict]:
    date = datetime.now().strftime("%Y-%m-%d")
    path = log_root / f"fleet-{date}.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# RuntimeConfig knob
# ---------------------------------------------------------------------------


def test_runtime_config_has_status_log_interval_default() -> None:
    from fleet.core.limits import STATUS_LOG_INTERVAL_SEC

    assert STATUS_LOG_INTERVAL_SEC == 30


def test_runtime_config_status_log_interval_override() -> None:
    from fleet.core.limits import STATUS_LOG_INTERVAL_SEC

    assert STATUS_LOG_INTERVAL_SEC == 30  # constant, cannot override per-instance


# ---------------------------------------------------------------------------
# _fleet_log_context snapshot fields
# ---------------------------------------------------------------------------


def test_fleet_log_context_includes_in_flight_count(tmp_path: Path) -> None:
    s = _make_supervisor(tmp_path, config=RuntimeConfig(max_concurrent=5))
    s.in_flight["t-001"] = None  # type: ignore[assignment]
    s.in_flight["t-002"] = None  # type: ignore[assignment]
    ctx = fleet_log_context(s.state)
    assert ctx["in_flight"] == 2
    assert ctx["cap"] == 5


def test_fleet_log_context_includes_usage_pct(tmp_path: Path) -> None:
    s = _make_supervisor(tmp_path)
    s.rate_gauge.update(
        Event(
            kind="rate_limit_info",
            raw={},
            ts=datetime.now(tz=UTC),
            rate_info={"usage_pct": 42.5},
        )
    )
    ctx = fleet_log_context(s.state)
    assert ctx["usage_pct"] == 42.5
    assert "threshold_pct" not in ctx  # usage is telemetry only; it gates nothing


def test_fleet_log_context_paused_until_null_when_unpaused(tmp_path: Path) -> None:
    s = _make_supervisor(tmp_path)
    assert fleet_log_context(s.state)["paused_until"] is None


def test_fleet_log_context_task_ids_sorted(tmp_path: Path) -> None:
    s = _make_supervisor(tmp_path)
    s.in_flight["t-z"] = None  # type: ignore[assignment]
    s.in_flight["t-a"] = None  # type: ignore[assignment]
    s.in_flight["t-m"] = None  # type: ignore[assignment]
    assert fleet_log_context(s.state)["task_ids"] == ["t-a", "t-m", "t-z"]


# ---------------------------------------------------------------------------
# Heartbeat emission via supervisor logger
# ---------------------------------------------------------------------------


def test_status_log_snapshot_emits_supervisor_status_event(tmp_path: Path) -> None:
    log_root = tmp_path / "logs"
    log = setup_supervisor_logger(log_root)
    s = _make_supervisor(tmp_path, log=log, config=RuntimeConfig(max_concurrent=3))
    s.rate_gauge.update(
        Event(
            kind="rate_limit_info",
            raw={},
            ts=datetime.now(tz=UTC),
            rate_info={"usage_pct": 17.0},
        )
    )

    asyncio.run(StatusLog().tick(s.state))

    records = _read_fleet_log(log_root)
    status_events = [r for r in records if r.get("event") == "supervisor_status"]
    assert len(status_events) == 1
    evt = status_events[0]
    assert evt["in_flight"] == 0
    assert evt["cap"] == 3
    assert evt["usage_pct"] == 17.0
    assert "threshold_pct" not in evt
    assert evt["task_ids"] == []
    assert evt["paused_until"] is None
    structlog.reset_defaults()


def test_status_log_loop_fires_at_interval(tmp_path: Path, monkeypatch) -> None:
    log_root = tmp_path / "logs"
    log = setup_supervisor_logger(log_root)
    s = _make_supervisor(tmp_path, log=log)
    svc = StatusLog(interval_sec=0.05)

    async def _run() -> None:
        serve_task = asyncio.create_task(svc.serve(s.state))
        # Wait long enough for two heartbeats to fire
        await asyncio.sleep(0.25)
        s.state.shutting_down = True
        try:
            await asyncio.wait_for(serve_task, timeout=2.0)
        except (asyncio.CancelledError, Exception):
            pass

    asyncio.run(_run())

    records = _read_fleet_log(log_root)
    status_events = [r for r in records if r.get("event") == "supervisor_status"]
    assert len(status_events) >= 2, f"expected >=2 heartbeats, got {len(status_events)}"
    structlog.reset_defaults()


def test_status_log_loop_exits_on_shutdown(tmp_path: Path, monkeypatch) -> None:
    s = _make_supervisor(tmp_path)
    svc = StatusLog(interval_sec=0.05)

    async def _run() -> bool:
        s.state.shutting_down = True
        try:
            await asyncio.wait_for(svc.serve(s.state), timeout=2.0)
            return True
        except TimeoutError:
            return False

    assert asyncio.run(_run()), "status loop did not exit when shutting_down was set"


# ---------------------------------------------------------------------------
# Outcome logs include fleet context fields
# ---------------------------------------------------------------------------


def test_task_completed_success_log_includes_usage_pct(tmp_path: Path) -> None:
    log_root = tmp_path / "logs"
    log = setup_supervisor_logger(log_root)
    s = _make_supervisor(tmp_path, log=log)
    s.rate_gauge.update(
        Event(
            kind="rate_limit_info",
            raw={},
            ts=datetime.now(tz=UTC),
            rate_info={"usage_pct": 55.0},
        )
    )
    s._queue = StubQueue(status="closed")
    s._handle_outcome(
        Task(id="t-001", title="X", description=None, status="closed"),
        TaskOutcomeRecord(outcome=TaskOutcome.SUCCESS, exit_code=0),
    )

    records = _read_fleet_log(log_root)
    noop = [r for r in records if r.get("event") == "task_noop_on_exit"]
    assert len(noop) == 1
    assert noop[0]["usage_pct"] == 55.0
    assert noop[0]["in_flight"] == 0
    structlog.reset_defaults()


def test_task_rate_limit_release_log_includes_in_flight(tmp_path: Path) -> None:
    log_root = tmp_path / "logs"
    log = setup_supervisor_logger(log_root)
    s = _make_supervisor(tmp_path, log=log)

    s._handle_outcome(
        Task(id="t-001", title="X", description=None, status="in_progress"),
        TaskOutcomeRecord(
            outcome=TaskOutcome.RATE_LIMIT, exit_code=None, resets_at=None
        ),
    )

    records = _read_fleet_log(log_root)
    rl = [r for r in records if r.get("event") == "task_rate_limit_release"]
    assert len(rl) == 1
    # fleet_ctx fields present
    assert "in_flight" in rl[0]
    assert "usage_pct" in rl[0]
    # task_rate_limit_release still uses its own paused_until (str(datetime))
    assert isinstance(rl[0]["paused_until"], str)
    structlog.reset_defaults()


def test_fleet_log_context_includes_context_tokens_key(tmp_path: Path) -> None:
    s = _make_supervisor(tmp_path)
    s.in_flight["t-001"] = None  # type: ignore[assignment]
    ctx = fleet_log_context(s.state)
    assert "context_tokens" in ctx
    assert isinstance(ctx["context_tokens"], dict)
    assert "t-001" in ctx["context_tokens"]
    # When no events.jsonl exists the value should be 0.
    assert ctx["context_tokens"]["t-001"] == 0


# ---------------------------------------------------------------------------
# Stall kill-and-retry ladder: warn vs kill actions
# ---------------------------------------------------------------------------


def _create_stale_events_file(tmp_path: Path, task_id: str, age_sec: float = 3600) -> None:
    import os
    import time

    task_dir = tmp_path / "tasks" / task_id
    attempt_dir = make_attempt(task_dir, 1)
    events_file = attempt_dir / "events.jsonl"
    events_file.touch()
    old_time = time.time() - age_sec
    os.utime(events_file, (old_time, old_time))


def test_stall_warn_action_never_kills(tmp_path: Path) -> None:
    """Default stall_action="warn" only warns; _stall_killed stays empty."""
    s = _make_supervisor(
        tmp_path,
        config=RuntimeConfig(stall_warning_minutes=1, stall_action="warn"),
    )
    _create_stale_events_file(tmp_path, "t-warn")

    class FakeRunner:
        def __init__(self) -> None:
            self.kill_calls = 0

        async def kill(self, reason: str = "manual_kill") -> None:
            self.kill_calls += 1

    fake = FakeRunner()
    s.in_flight["t-warn"] = object()  # type: ignore[assignment]
    s._runners["t-warn"] = fake  # type: ignore[assignment]

    s._log_status_snapshot()

    assert "t-warn" in s._stall_warned
    assert "t-warn" not in s._stall_killed
    assert len(s._stall_killed) == 0
    assert fake.kill_calls == 0
    structlog.reset_defaults()


def test_stall_kill_action_schedules_runner_kill(tmp_path: Path) -> None:
    """stall_action="kill" records the task and schedules runner.kill()."""
    s_holder: dict = {}

    async def _run() -> None:
        import structlog as _structlog

        s = _make_supervisor(
            tmp_path,
            config=RuntimeConfig(stall_warning_minutes=1, stall_action="kill"),
        )
        _create_stale_events_file(tmp_path, "t-kill")

        class FakeRunner:
            def __init__(self) -> None:
                self.kill_calls = 0

            async def kill(self, reason: str = "manual_kill") -> None:
                self.kill_calls += 1

        fake = FakeRunner()
        s.in_flight["t-kill"] = object()  # type: ignore[assignment]
        s._runners["t-kill"] = fake  # type: ignore[assignment]

        s._log_status_snapshot()
        # Let the scheduled kill() coroutine execute.
        await asyncio.sleep(0.2)
        s_holder["s"] = s
        s_holder["fake"] = fake
        _structlog.reset_defaults()

    asyncio.run(_run())

    assert "t-kill" in s_holder["s"]._stall_killed
    assert s_holder["fake"].kill_calls == 1
