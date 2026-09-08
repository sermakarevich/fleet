"""Tests for orchestrator/status_log.py: heartbeat tick and fleet_log_context."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import structlog

from fleet.core.config import RuntimeConfig
from fleet.core.limits import STATUS_LOG_INTERVAL_SEC
from fleet.core.task import Event
from fleet.orchestrator.status_log import StatusLog, fleet_log_context
from fleet.state.journal import setup_supervisor_logger
from tests.conftest import make_supervisor


def _read_fleet_log(log_root: Path) -> list[dict]:
    date = datetime.now().strftime("%Y-%m-%d")
    path = log_root / f"fleet-{date}.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def test_fleet_log_context_keys(tmp_path: Path) -> None:
    """fleet_log_context(st) carries the same keys as the old snapshot."""
    sup = make_supervisor(tmp_path, services=[], checks=[])
    ctx = fleet_log_context(sup.state)
    assert ctx["in_flight"] == 0
    assert ctx["cap"] == sup.state.config.max_concurrent
    assert "usage_pct" in ctx
    assert ctx["paused_until"] is None
    assert "rate_limit_resets_at" in ctx
    assert ctx["task_ids"] == []
    assert ctx["context_tokens"] == {}


def test_fleet_log_context_in_flight_and_tokens(tmp_path: Path) -> None:
    """In-flight ids are sorted and each gets a context_tokens entry."""
    sup = make_supervisor(
        tmp_path, services=[], checks=[], config=RuntimeConfig(max_concurrent=5)
    )
    sup.state.in_flight["t-z"] = None  # type: ignore[assignment]
    sup.state.in_flight["t-a"] = None  # type: ignore[assignment]
    ctx = fleet_log_context(sup.state)
    assert ctx["in_flight"] == 2
    assert ctx["cap"] == 5
    assert ctx["task_ids"] == ["t-a", "t-z"]
    assert ctx["context_tokens"] == {"t-z": 0, "t-a": 0}


def test_fleet_log_context_usage_pct(tmp_path: Path) -> None:
    """usage_pct reflects the rate gauge reading."""
    sup = make_supervisor(tmp_path, services=[], checks=[])
    sup.state.rate_gauge.update(
        Event(
            kind="rate_limit_info",
            raw={},
            ts=datetime.now(tz=UTC),
            rate_info={"usage_pct": 42.5},
        )
    )
    assert fleet_log_context(sup.state)["usage_pct"] == 42.5


def test_tick_emits_supervisor_status(tmp_path: Path) -> None:
    """StatusLog.tick logs one supervisor_status line with the context keys."""
    log_root = tmp_path / "logs"
    log = setup_supervisor_logger(log_root)
    sup = make_supervisor(
        tmp_path,
        services=[],
        checks=[],
        config=RuntimeConfig(max_concurrent=3),
    )
    sup.state.log = log
    sup.state.rate_gauge.update(
        Event(
            kind="rate_limit_info",
            raw={},
            ts=datetime.now(tz=UTC),
            rate_info={"usage_pct": 17.0},
        )
    )

    asyncio.run(StatusLog().tick(sup.state))

    records = _read_fleet_log(log_root)
    status_events = [r for r in records if r.get("event") == "supervisor_status"]
    assert len(status_events) == 1
    evt = status_events[0]
    assert evt["in_flight"] == 0
    assert evt["cap"] == 3
    assert evt["usage_pct"] == 17.0
    assert evt["task_ids"] == []
    assert evt["paused_until"] is None
    assert "context_tokens" in evt
    structlog.reset_defaults()


def test_serve_ticks_until_shutdown(tmp_path: Path) -> None:
    """serve() with a small interval emits heartbeats then stops on shutdown."""
    log_root = tmp_path / "logs"
    log = setup_supervisor_logger(log_root)
    sup = make_supervisor(tmp_path, services=[], checks=[])
    sup.state.log = log
    svc = StatusLog(interval_sec=0.05)

    async def _run() -> None:
        task = asyncio.create_task(svc.serve(sup.state))
        await asyncio.sleep(0.2)
        sup.state.shutting_down = True
        await asyncio.wait_for(task, timeout=2.0)

    asyncio.run(_run())
    records = _read_fleet_log(log_root)
    status_events = [r for r in records if r.get("event") == "supervisor_status"]
    assert len(status_events) >= 2, f"expected >=2 heartbeats, got {len(status_events)}"
    structlog.reset_defaults()


def test_default_interval_matches_limits() -> None:
    """Default interval comes from core/limits.py; ctor arg overrides it."""
    assert StatusLog().interval_sec == STATUS_LOG_INTERVAL_SEC
    assert StatusLog(interval_sec=0.01).interval_sec == 0.01
