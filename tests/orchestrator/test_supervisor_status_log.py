"""Tests for the status heartbeat service (unit under test: orchestrator/status_log.py)."""

from __future__ import annotations

import asyncio
import json
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path

import structlog

from fleet.core.config import RuntimeConfig
from fleet.core.limits import STATUS_LOG_INTERVAL_SEC
from fleet.core.task import Event, Task, TaskOutcome, TaskOutcomeRecord
from fleet.orchestrator.reap import handle_outcome
from fleet.orchestrator.status_log import fleet_log_context, make_status_log, status_log_tick
from fleet.orchestrator.supervisor import Supervisor
from fleet.state import attempts as attempts_mod
from fleet.state.journal import setup_supervisor_logger
from tests.conftest import make_running_worker, make_supervisor
from tests.helpers.wait import await_until

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
    sup = make_supervisor(tmp_path, queue=StubQueue(), config=config, services=[], checks=[])  # type: ignore[arg-type]
    if log is not None:
        sup.state.log = log
    return sup


def _handle(s: Supervisor, task: Task, record: TaskOutcomeRecord) -> None:
    """Fold one outcome through reap, opening a fresh attempt like spawn does."""

    n = attempts_mod.record_start(
        s.state.task_dir_for(task.id), coder="c", model="m", worker="task.fresh"
    )
    worker = make_running_worker(task.id, None, task=task, attempt_n=n)
    handle_outcome(s.state, worker, record)


def _heartbeat_count(log_root: Path) -> int:
    """Supervisor-status heartbeats visible in the flushed log file."""
    return len([r for r in _read_fleet_log(log_root) if r.get("event") == "supervisor_status"])


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

    assert STATUS_LOG_INTERVAL_SEC == 30


def test_runtime_config_status_log_interval_override() -> None:

    assert STATUS_LOG_INTERVAL_SEC == 30  # constant, cannot override per-instance


# ---------------------------------------------------------------------------
# _fleet_log_context snapshot fields
# ---------------------------------------------------------------------------


def test_fleet_log_context_includes_in_flight_count(tmp_path: Path) -> None:
    s = _make_supervisor(tmp_path, config=RuntimeConfig(max_concurrent=5))
    s.state.running["t-001"] = make_running_worker("t-001", tmp_path)
    s.state.running["t-002"] = make_running_worker("t-002", tmp_path)
    ctx = fleet_log_context(s.state)
    assert ctx["in_flight"] == 2
    assert ctx["cap"] == 5


def test_fleet_log_context_includes_usage_pct(tmp_path: Path) -> None:
    s = _make_supervisor(tmp_path)
    s.state.rate_gauge.update(
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
    s.state.running["t-z"] = make_running_worker("t-z", tmp_path)
    s.state.running["t-a"] = make_running_worker("t-a", tmp_path)
    s.state.running["t-m"] = make_running_worker("t-m", tmp_path)
    assert fleet_log_context(s.state)["task_ids"] == ["t-a", "t-m", "t-z"]


# ---------------------------------------------------------------------------
# Heartbeat emission via supervisor logger
# ---------------------------------------------------------------------------


def test_status_log_snapshot_emits_supervisor_status_event(tmp_path: Path) -> None:
    log_root = tmp_path / "logs"
    log = setup_supervisor_logger(log_root)
    s = _make_supervisor(tmp_path, log=log, config=RuntimeConfig(max_concurrent=3))
    s.state.rate_gauge.update(
        Event(
            kind="rate_limit_info",
            raw={},
            ts=datetime.now(tz=UTC),
            rate_info={"usage_pct": 17.0},
        )
    )

    asyncio.run(status_log_tick(s.state))

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
    svc = make_status_log(interval_sec=0.05)

    async def _run() -> None:
        serve_task = asyncio.create_task(svc.serve(s.state))
        # Heartbeats flush per record: wait for two in the log file itself.
        assert await await_until(lambda: _heartbeat_count(log_root) >= 2), "fewer than 2 heartbeats"
        s.state.shutting_down = True
        with suppress(asyncio.CancelledError, Exception):
            await asyncio.wait_for(serve_task, timeout=2.0)

    asyncio.run(_run())

    records = _read_fleet_log(log_root)
    status_events = [r for r in records if r.get("event") == "supervisor_status"]
    assert len(status_events) >= 2, f"expected >=2 heartbeats, got {len(status_events)}"
    structlog.reset_defaults()


def test_status_log_loop_exits_on_shutdown(tmp_path: Path, monkeypatch) -> None:
    s = _make_supervisor(tmp_path)
    svc = make_status_log(interval_sec=0.05)

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


def test_task_completed_success_log_binds_task_fields(tmp_path: Path) -> None:
    log_root = tmp_path / "logs"
    log = setup_supervisor_logger(log_root)
    s = _make_supervisor(tmp_path, log=log)
    s.state.rate_gauge.update(
        Event(
            kind="rate_limit_info",
            raw={},
            ts=datetime.now(tz=UTC),
            rate_info={"usage_pct": 55.0},
        )
    )
    s.state.queue = StubQueue(status="closed")
    _handle(
        s,
        Task(id="t-001", title="X", description=None, status="closed"),
        TaskOutcomeRecord(outcome=TaskOutcome.SUCCESS, exit_code=0),
    )

    records = _read_fleet_log(log_root)
    noop = [r for r in records if r.get("event") == "task_noop_on_exit"]
    assert len(noop) == 1
    # Per-task lines bind task fields once; fleet telemetry (usage_pct,
    # in_flight) stays on the supervisor_status heartbeat only.
    assert noop[0]["task_id"] == "t-001"
    assert "usage_pct" not in noop[0]
    assert "in_flight" not in noop[0]
    structlog.reset_defaults()


def test_task_rate_limit_release_log_binds_task_fields(tmp_path: Path) -> None:
    log_root = tmp_path / "logs"
    log = setup_supervisor_logger(log_root)
    s = _make_supervisor(tmp_path, log=log)

    _handle(
        s,
        Task(id="t-001", title="X", description=None, status="in_progress"),
        TaskOutcomeRecord(outcome=TaskOutcome.RATE_LIMIT, exit_code=None, resets_at=None),
    )

    records = _read_fleet_log(log_root)
    rl = [r for r in records if r.get("event") == "task_rate_limit_release"]
    assert len(rl) == 1
    # Per-task lines bind task fields once; fleet telemetry stays on the
    # supervisor_status heartbeat.
    assert rl[0]["task_id"] == "t-001"
    assert "in_flight" not in rl[0]
    assert "usage_pct" not in rl[0]
    # task_rate_limit_release still uses its own paused_until (str(datetime))
    assert isinstance(rl[0]["paused_until"], str)
    structlog.reset_defaults()


def test_fleet_log_context_includes_context_tokens_key(tmp_path: Path) -> None:
    s = _make_supervisor(tmp_path)
    s.state.running["t-001"] = make_running_worker("t-001", tmp_path)
    ctx = fleet_log_context(s.state)
    assert "context_tokens" in ctx
    assert isinstance(ctx["context_tokens"], dict)
    assert "t-001" in ctx["context_tokens"]
    # When no events.jsonl exists the value should be 0.
    assert ctx["context_tokens"]["t-001"] == 0
