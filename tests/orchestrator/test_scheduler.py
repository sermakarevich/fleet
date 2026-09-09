"""Tests for orchestrator/scheduler.py: the tick that opens due schedules."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fleet.core.clock import FakeClock
from fleet.core.limits import SCHEDULER_TICK_SEC
from fleet.orchestrator import default_services
from fleet.orchestrator.scheduler import make_scheduler, scheduler_tick
from fleet.orchestrator.service import ServiceOrder
from fleet.schedules.model import Schedule
from fleet.schedules.store import ScheduleStore
from tests.conftest import FakeQueue, make_supervisor

CREATED = "2026-09-09T00:00:00+00:00"
DUE = datetime(2026, 9, 9, 0, 1, tzinfo=UTC)


def _schedule(**overrides) -> Schedule:
    """One every-minute schedule due at 00:01 unless overridden."""
    data = {
        "id": "sch-abc123",
        "name": "nightly",
        "cron": "* * * * *",
        "title": "Nightly triage",
        "description": "triage the inbox",
        "cwd": "/repo",
        "coder": "claude",
        "model": "opus",
        "created_at": CREATED,
        "updated_at": CREATED,
    }
    data.update(overrides)
    return Schedule.from_dict(data)


def _run_lines(tmp_path: Path) -> list[str]:
    """Raw lines of the schedule's run-history file."""
    path = tmp_path / "schedules" / "sch-abc123.runs.jsonl"
    return path.read_text(encoding="utf-8").splitlines()


def _state(tmp_path: Path, **overrides):
    """Supervisor state over tmp_path with a FakeQueue and a FakeClock at DUE."""
    queue = FakeQueue()
    sup = make_supervisor(tmp_path, queue=queue, services=[], checks=[])
    st = sup.state
    st.clock = FakeClock(start=DUE)
    ScheduleStore(tmp_path).save(_schedule(**overrides))
    return st, queue


def test_factory_defaults_and_override() -> None:
    """Default cadence is SCHEDULER_TICK_SEC; factory arg overrides it."""
    svc = make_scheduler()
    assert svc.name == "scheduler"
    assert svc.order == ServiceOrder.Schedule
    assert svc.interval_sec == SCHEDULER_TICK_SEC
    assert svc.tick is scheduler_tick
    assert svc.on_start is scheduler_tick
    assert make_scheduler(interval_sec=0.01).interval_sec == 0.01


def test_due_schedule_opens_task_and_records_run(tmp_path: Path) -> None:
    """A due schedule opens one bead and appends one run line."""
    st, queue = _state(tmp_path)

    asyncio.run(scheduler_tick(st))

    assert len(queue._tasks) == 1
    task = next(iter(queue._tasks.values()))
    assert task.title == "Nightly triage"
    assert task.cwd == "/repo"
    assert task.coder == "claude"
    assert task.model == "opus"
    assert len(_run_lines(tmp_path)) == 1


def test_second_tick_at_same_clock_opens_nothing(tmp_path: Path) -> None:
    """The same clock minute fires once; a repeat tick is a no-op."""
    st, queue = _state(tmp_path)

    asyncio.run(scheduler_tick(st))
    asyncio.run(scheduler_tick(st))

    assert len(queue._tasks) == 1
    assert len(_run_lines(tmp_path)) == 1


def test_paused_supervisor_opens_nothing(tmp_path: Path) -> None:
    """A future paused_until skips the tick entirely (no task, no run)."""
    st, queue = _state(tmp_path)
    st.paused_until = DUE + timedelta(minutes=5)

    asyncio.run(scheduler_tick(st))

    assert len(queue._tasks) == 0
    assert not (tmp_path / "schedules" / "sch-abc123.runs.jsonl").exists()


def test_pause_file_opens_nothing(tmp_path: Path) -> None:
    """A present .pause file skips the tick entirely."""
    st, queue = _state(tmp_path)
    (tmp_path / ".pause").touch()

    asyncio.run(scheduler_tick(st))

    assert len(queue._tasks) == 0
    assert not (tmp_path / "schedules" / "sch-abc123.runs.jsonl").exists()


def test_intervals_override_matches_scheduler_name(tmp_path: Path) -> None:
    """make_supervisor intervals={"scheduler": ...} still applies by name."""
    sup = make_supervisor(tmp_path, intervals={"scheduler": 0.01})
    svc = next(s for s in sup.state.services if s.name == "scheduler")
    assert svc.interval_sec == 0.01


def test_default_services_contains_scheduler() -> None:
    """default_services() wires the scheduler after leases, before claim."""
    names = [svc.name for svc in default_services()]
    assert "scheduler" in names
    assert names.index("lease_reconcile") < names.index("scheduler") < names.index("claim")
