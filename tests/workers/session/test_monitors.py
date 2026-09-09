"""Tests for workers/session/monitors.py: one test per monitor, no subprocess."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import structlog

from fleet.core.config import RuntimeConfig
from fleet.core.task import Event, Task, TaskOutcome, TaskOutcomeRecord
from fleet.state.paths import CHECKPOINT_REQUESTED_MARKER
from fleet.state.run_file import RunRecord
from fleet.workers.base import StepContext
from fleet.workers.session.monitors import (
    AttemptBudget,
    ContextErrorScanner,
    ContextGauge,
    HealthProbe,
    LeaseHeartbeat,
    MonitorContext,
    RateGaugeFeeder,
    SessionEventLogger,
    build_monitors,
)


class _StubCoder:
    name = "stub"
    context_limit = 1_000

    def __init__(self) -> None:
        self.probe_calls: list[datetime] = []

    def probe_health(self, task, task_dir, since, session_id=None):
        self.probe_calls.append(since)


class _Gauge:
    def __init__(self) -> None:
        self.updates: list[Event] = []

    def update(self, evt: Event) -> None:
        self.updates.append(evt)


def _event(kind: str, **fields) -> Event:
    return Event(kind=kind, raw=fields.pop("raw", {}), ts=datetime.now(tz=UTC), **fields)


def _ctx(tmp_path: Path, task: Task | None = None, **overrides) -> MonitorContext:
    now = datetime.now(tz=UTC)
    attempt_dir = tmp_path / "attempts" / "1"
    attempt_dir.mkdir(parents=True, exist_ok=True)
    base: dict = {
        "task": task or Task(id="t", title="T", description=None, status="in_progress"),
        "task_dir": tmp_path,
        "attempt_dir": attempt_dir,
        "coder": _StubCoder(),
        "config": RuntimeConfig(),
        "rate_gauge": _Gauge(),
        "task_log": structlog.get_logger(),
        "ctx_log": structlog.get_logger(),
        "context_limit": 1_000,
        "checkpoint_pct": 75,
        "kill_pct": 90,
        "attempt_budget_sec": None,
        "started_at": now,
        "last_event_at": now,
        "last_stdout_at": now,
        "last_probe_at": now,
    }
    base.update(overrides)
    return MonitorContext(**base)


def test_build_monitors_sorted_by_order(tmp_path: Path) -> None:
    step = StepContext(
        task=Task(id="t", title="T", description=None, status="in_progress"),
        task_dir=tmp_path,
        project_root=tmp_path,
        fleet_home=tmp_path,
        coder=_StubCoder(),
        config=RuntimeConfig(),
        rate_gauge=_Gauge(),
        log=structlog.get_logger(),
        attempt_dir=tmp_path / "attempts" / "1",
        attempt_n=1,
    )
    monitors, state = build_monitors(step, structlog.get_logger(), step.attempt_dir)
    assert [m.order for m in monitors] == sorted(m.order for m in monitors)
    assert len(monitors) == 7
    assert state.context_limit == 1_000
    assert state.checkpoint_written is False


def test_session_event_logger_returns_none(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    monitor = SessionEventLogger()
    assert monitor.on_event(_event("session_started"), ctx) is None
    assert monitor.on_event(_event("session_started"), ctx) is None
    assert monitor.on_event(_event("tool_use", tool_name="bash"), ctx) is None
    assert monitor.on_event(_event("session_ended"), ctx) is None


def test_rate_gauge_feeder(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    monitor = RateGaugeFeeder()
    evt = _event("rate_limit_info", rate_info={"usage_pct": 50.0})
    assert monitor.on_event(evt, ctx) is None
    assert monitor.on_event(_event("assistant_text"), ctx) is None
    assert ctx.rate_gauge.updates == [evt]


def test_context_gauge_checkpoint_then_kill(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    monitor = ContextGauge()
    assert monitor.on_event(_event("assistant_text", usage={"input_tokens": 800}), ctx) is None
    assert (ctx.attempt_dir / CHECKPOINT_REQUESTED_MARKER).exists()
    assert ctx.peak_context_tokens == 800
    verdict = monitor.on_event(_event("assistant_text", usage={"input_tokens": 950}), ctx)
    assert verdict is not None
    assert verdict.outcome == TaskOutcome.CONTEXT_PRESSURE
    assert verdict.kill is True
    assert "kill" in verdict.reason


def test_context_gauge_ignores_session_ended_usage(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    monitor = ContextGauge()
    assert monitor.on_event(_event("session_ended", usage={"input_tokens": 999}), ctx) is None
    assert ctx.peak_context_tokens == 0
    assert not (ctx.attempt_dir / CHECKPOINT_REQUESTED_MARKER).exists()


def test_attempt_budget_kills_when_over(tmp_path: Path) -> None:
    now = datetime.now(tz=UTC)
    ctx = _ctx(
        tmp_path,
        task=Task(id="t", title="T", description=None, status="in_progress", max_attempt_minutes=1),
        attempt_budget_sec=60.0,
        started_at=now - timedelta(hours=2),
    )
    monitor = AttemptBudget()
    verdict = monitor.on_tick(now, ctx)
    assert verdict is not None
    assert verdict.outcome == TaskOutcome.KILLED
    assert verdict.reason == "timeout"
    assert monitor.on_event(_event("assistant_text"), ctx) == verdict


def test_attempt_budget_quiet_when_fresh_or_disabled(tmp_path: Path) -> None:
    monitor = AttemptBudget()
    assert monitor.on_tick(datetime.now(tz=UTC), _ctx(tmp_path)) is None
    disabled = _ctx(
        tmp_path,
        started_at=datetime.now(tz=UTC) - timedelta(hours=2),
        attempt_budget_sec=None,
    )
    assert monitor.on_tick(datetime.now(tz=UTC), disabled) is None


def test_context_error_scanner(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    monitor = ContextErrorScanner()
    overflow = _event("error", raw={"message": "Error: prompt is too long"})
    verdict = monitor.on_event(overflow, ctx)
    assert verdict is not None
    assert verdict.outcome == TaskOutcome.CONTEXT_PRESSURE
    assert verdict.reason == "cli reported context overflow"
    prose = _event("assistant_text", raw={"message": "prompt is too long, they say"})
    assert monitor.on_event(prose, ctx) is None


def test_health_probe_rate_limit_event(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    monitor = HealthProbe()
    rejected = _event("rate_limit", rate_info={"status": "rejected", "resets_at": 123})
    verdict = monitor.on_event(rejected, ctx)
    assert verdict is not None
    assert verdict.outcome == TaskOutcome.RATE_LIMIT
    assert verdict.resets_at == 123
    assert "123" in verdict.reason
    waiting = _event("rate_limit", rate_info={"status": "waiting"})
    assert monitor.on_event(waiting, ctx) is None


def test_health_probe_tick_kills_on_provider_error(tmp_path: Path) -> None:
    now = datetime.now(tz=UTC)
    coder = _StubCoder()
    record = TaskOutcomeRecord(outcome=TaskOutcome.FAILURE, reason="socket hangup")

    def _probing(task, task_dir, since, session_id=None):
        coder.probe_calls.append(since)
        return record

    coder.probe_health = _probing
    ctx = _ctx(
        tmp_path,
        coder=coder,
        last_stdout_at=now - timedelta(seconds=400),
        last_probe_at=now - timedelta(seconds=400),
    )
    verdict = asyncio.run(HealthProbe().on_tick(now, ctx))
    assert verdict is not None
    assert verdict.outcome == TaskOutcome.FAILURE
    assert verdict.reason == "socket hangup"
    assert coder.probe_calls == [ctx.last_stdout_at]


def test_health_probe_tick_spares_cli_still_retrying(tmp_path: Path) -> None:
    now = datetime.now(tz=UTC)
    coder = _StubCoder()

    def _limited(task, task_dir, since, session_id=None):
        return TaskOutcomeRecord(outcome=TaskOutcome.RATE_LIMIT, reason="provider rate limit")

    coder.probe_health = _limited
    ctx = _ctx(
        tmp_path,
        coder=coder,
        last_stdout_at=now - timedelta(seconds=100),
        last_probe_at=now - timedelta(seconds=400),
    )
    assert asyncio.run(HealthProbe().on_tick(now, ctx)) is None


def test_health_probe_tick_quiet_when_recent(tmp_path: Path) -> None:
    now = datetime.now(tz=UTC)
    ctx = _ctx(tmp_path, last_stdout_at=now, last_probe_at=now)
    assert asyncio.run(HealthProbe().on_tick(now, ctx)) is None
    assert ctx.coder.probe_calls == []


def test_lease_heartbeat_refreshes_run_json(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    now = datetime.now(tz=UTC)
    assert LeaseHeartbeat().on_tick(now, ctx) is None
    record = RunRecord.load(ctx.attempt_dir)
    assert record is not None
    assert record.heartbeat_at is not None
    assert record.lease_until is not None
    assert record.lease_until > record.heartbeat_at
