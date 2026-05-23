from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import structlog

from fleet.logging_setup import setup_supervisor_logger
from fleet.schemas import Event, RuntimeConfig, Task, TaskOutcome, TaskOutcomeRecord
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
    def __init__(self, status: str = "in_progress") -> None:
        self._status = status

    def claim_next(self, claimer_id):
        return None

    def release(self, task_id, reason=""):
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
    cfg = RuntimeConfig()
    assert cfg.status_log_interval_sec == 30


def test_runtime_config_status_log_interval_override() -> None:
    cfg = RuntimeConfig(status_log_interval_sec=5)
    assert cfg.status_log_interval_sec == 5


# ---------------------------------------------------------------------------
# _fleet_log_context snapshot fields
# ---------------------------------------------------------------------------


def test_fleet_log_context_includes_in_flight_count(tmp_path: Path) -> None:
    s = _make_supervisor(tmp_path, config=RuntimeConfig(max_concurrent=5))
    s.in_flight["t-001"] = None  # type: ignore[assignment]
    s.in_flight["t-002"] = None  # type: ignore[assignment]
    ctx = s._fleet_log_context()
    assert ctx["in_flight"] == 2
    assert ctx["cap"] == 5


def test_fleet_log_context_includes_usage_pct(tmp_path: Path) -> None:
    s = _make_supervisor(tmp_path, config=RuntimeConfig(rate_limit_threshold_pct=90))
    s.rate_gauge.update(
        Event(
            kind="rate_limit_info",
            raw={},
            ts=datetime.now(tz=timezone.utc),
            rate_info={"usage_pct": 42.5},
        )
    )
    ctx = s._fleet_log_context()
    assert ctx["usage_pct"] == 42.5
    assert ctx["threshold_pct"] == 90


def test_fleet_log_context_paused_until_null_when_unpaused(tmp_path: Path) -> None:
    s = _make_supervisor(tmp_path)
    assert s._fleet_log_context()["paused_until"] is None


def test_fleet_log_context_task_ids_sorted(tmp_path: Path) -> None:
    s = _make_supervisor(tmp_path)
    s.in_flight["t-z"] = None  # type: ignore[assignment]
    s.in_flight["t-a"] = None  # type: ignore[assignment]
    s.in_flight["t-m"] = None  # type: ignore[assignment]
    assert s._fleet_log_context()["task_ids"] == ["t-a", "t-m", "t-z"]


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
            ts=datetime.now(tz=timezone.utc),
            rate_info={"usage_pct": 17.0},
        )
    )

    s._log_status_snapshot()

    records = _read_fleet_log(log_root)
    status_events = [r for r in records if r.get("event") == "supervisor_status"]
    assert len(status_events) == 1
    evt = status_events[0]
    assert evt["in_flight"] == 0
    assert evt["cap"] == 3
    assert evt["usage_pct"] == 17.0
    assert evt["threshold_pct"] == 90
    assert evt["task_ids"] == []
    assert evt["paused_until"] is None
    structlog.reset_defaults()


def test_status_log_loop_fires_at_interval(tmp_path: Path) -> None:
    log_root = tmp_path / "logs"
    log = setup_supervisor_logger(log_root)
    s = _make_supervisor(tmp_path, log=log, config=RuntimeConfig(status_log_interval_sec=1))

    async def _run() -> None:
        loop_task = asyncio.create_task(s._status_log_loop())
        # Wait long enough for two heartbeats to fire
        await asyncio.sleep(2.2)
        s._shutting_down = True
        loop_task.cancel()
        try:
            await loop_task
        except (asyncio.CancelledError, Exception):
            pass

    asyncio.run(_run())

    records = _read_fleet_log(log_root)
    status_events = [r for r in records if r.get("event") == "supervisor_status"]
    assert len(status_events) >= 2, f"expected >=2 heartbeats, got {len(status_events)}"
    structlog.reset_defaults()


def test_status_log_loop_exits_on_shutdown(tmp_path: Path) -> None:
    s = _make_supervisor(tmp_path, config=RuntimeConfig(status_log_interval_sec=1))

    async def _run() -> bool:
        s._shutting_down = True
        try:
            await asyncio.wait_for(s._status_log_loop(), timeout=2.0)
            return True
        except asyncio.TimeoutError:
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
            ts=datetime.now(tz=timezone.utc),
            rate_info={"usage_pct": 55.0},
        )
    )
    s._queue = StubQueue(status="closed")
    s._handle_outcome(
        Task(id="t-001", title="X", description=None, status="closed"),
        TaskOutcomeRecord(outcome=TaskOutcome.SUCCESS, exit_code=0),
    )

    records = _read_fleet_log(log_root)
    success = [r for r in records if r.get("event") == "task_completed_success"]
    assert len(success) == 1
    assert success[0]["usage_pct"] == 55.0
    assert success[0]["in_flight"] == 0
    structlog.reset_defaults()


def test_task_rate_limit_release_log_includes_in_flight(tmp_path: Path) -> None:
    log_root = tmp_path / "logs"
    log = setup_supervisor_logger(log_root)
    s = _make_supervisor(tmp_path, log=log, config=RuntimeConfig(rate_limit_default_sleep_sec=60))

    s._handle_outcome(
        Task(id="t-001", title="X", description=None, status="in_progress"),
        TaskOutcomeRecord(outcome=TaskOutcome.RATE_LIMIT, exit_code=None, resets_at=None),
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
