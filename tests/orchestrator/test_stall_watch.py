"""Tests for orchestrator/stall.py::StallWatch. Mirrors the source path."""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path

from fleet.core.config import RuntimeConfig
from fleet.core.task import TaskOutcome, TaskOutcomeRecord
from fleet.orchestrator.stall import StallWatch
from tests.conftest import make_running_worker, make_supervisor
from tests.helpers.task_dir import make_attempt


def _stale_events_file(base: Path, task_id: str, age_sec: float = 120) -> Path:
    task_dir = base / "tasks" / task_id
    attempt_dir = make_attempt(task_dir, 1)
    events_file = attempt_dir / "events.jsonl"
    events_file.touch()
    old_time = time.time() - age_sec
    os.utime(events_file, (old_time, old_time))
    return events_file


class _FakeRunner:
    """Stand-in for WorkerRun that records kill() calls."""

    def __init__(self) -> None:
        self.kill_calls = 0

    async def kill(self, reason: str = "manual_kill") -> None:
        self.kill_calls += 1


def test_warn_once_no_duplicate(tmp_path: Path) -> None:
    """A quiet worker is warned about once; repeat ticks do not re-warn."""
    sup = make_supervisor(
        tmp_path,
        config=RuntimeConfig(stall_warning_minutes=1, stall_action="warn"),
        services=[],
        checks=[],
    )
    svc = StallWatch()
    _stale_events_file(tmp_path, "t-stalled")
    sup.state.running["t-stalled"] = make_running_worker("t-stalled", tmp_path)

    asyncio.run(svc.tick(sup.state))
    assert "t-stalled" in svc._warned

    asyncio.run(svc.tick(sup.state))
    assert "t-stalled" in svc._warned
    assert len(svc._warned) == 1


def test_mtime_refresh_clears_warning(tmp_path: Path) -> None:
    """A worker that writes again leaves the warned set."""
    sup = make_supervisor(
        tmp_path,
        config=RuntimeConfig(stall_warning_minutes=1, stall_action="warn"),
        services=[],
        checks=[],
    )
    svc = StallWatch()
    events_file = _stale_events_file(tmp_path, "t-recover")
    sup.state.running["t-recover"] = make_running_worker("t-recover", tmp_path)

    asyncio.run(svc.tick(sup.state))
    assert "t-recover" in svc._warned

    os.utime(events_file, None)
    asyncio.run(svc.tick(sup.state))
    assert "t-recover" not in svc._warned


def test_warn_action_never_kills(tmp_path: Path) -> None:
    """stall_action="warn" only warns; nothing is killed."""
    sup = make_supervisor(
        tmp_path,
        config=RuntimeConfig(stall_warning_minutes=1, stall_action="warn"),
        services=[],
        checks=[],
    )
    svc = StallWatch()
    _stale_events_file(tmp_path, "t-warn")
    fake = _FakeRunner()
    sup.state.running["t-warn"] = make_running_worker("t-warn", tmp_path, run=fake)

    asyncio.run(svc.tick(sup.state))

    assert "t-warn" in svc._warned
    assert "t-warn" not in svc._killed
    assert fake.kill_calls == 0


def test_kill_action_kills_once(tmp_path: Path) -> None:
    """stall_action="kill" records the task and schedules one runner kill."""
    sup = make_supervisor(
        tmp_path,
        config=RuntimeConfig(stall_warning_minutes=1, stall_action="kill"),
        services=[],
        checks=[],
    )
    svc = StallWatch()
    _stale_events_file(tmp_path, "t-kill")
    fake = _FakeRunner()
    sup.state.running["t-kill"] = make_running_worker("t-kill", tmp_path, run=fake)

    async def _run() -> None:
        await svc.tick(sup.state)
        await asyncio.sleep(0.2)  # let the scheduled kill() run

    asyncio.run(_run())

    assert "t-kill" in svc._warned
    assert "t-kill" in svc._killed
    assert fake.kill_calls == 1


def test_on_worker_finished_clears_sets(tmp_path: Path) -> None:
    """StallWatch never keeps an id after on_worker_finished."""
    sup = make_supervisor(
        tmp_path,
        config=RuntimeConfig(stall_warning_minutes=1, stall_action="kill"),
        services=[],
        checks=[],
    )
    svc = StallWatch()
    _stale_events_file(tmp_path, "t-done")
    worker = make_running_worker("t-done", tmp_path, run=_FakeRunner())
    sup.state.running["t-done"] = worker

    async def _run() -> None:
        await svc.tick(sup.state)
        assert "t-done" in svc._warned
        await svc.on_worker_finished(
            sup.state, worker, TaskOutcomeRecord(outcome=TaskOutcome.SUCCESS)
        )

    asyncio.run(_run())

    assert "t-done" not in svc._warned
    assert "t-done" not in svc._killed


def test_zero_disables_check(tmp_path: Path) -> None:
    """stall_warning_minutes=0 keeps both sets empty."""
    sup = make_supervisor(
        tmp_path, config=RuntimeConfig(stall_warning_minutes=0), services=[], checks=[]
    )
    svc = StallWatch()
    _stale_events_file(tmp_path, "t-disabled", age_sec=600)
    sup.state.running["t-disabled"] = make_running_worker("t-disabled", tmp_path)

    asyncio.run(svc.tick(sup.state))

    assert svc._warned == set()
    assert svc._killed == set()


def test_missing_events_file_no_entry(tmp_path: Path) -> None:
    """A task dir without events.jsonl warns about nothing and raises nothing."""
    sup = make_supervisor(
        tmp_path, config=RuntimeConfig(stall_warning_minutes=1), services=[], checks=[]
    )
    svc = StallWatch()
    (tmp_path / "tasks" / "t-no-events").mkdir(parents=True)
    sup.state.running["t-no-events"] = make_running_worker("t-no-events", tmp_path)

    asyncio.run(svc.tick(sup.state))

    assert "t-no-events" not in svc._warned
