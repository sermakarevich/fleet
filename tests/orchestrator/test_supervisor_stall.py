from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path

import structlog

from fleet.core.config import RuntimeConfig
from fleet.orchestrator.stall import StallWatch
from fleet.orchestrator.supervisor import Supervisor
from fleet.state.journal import setup_supervisor_logger
from tests.conftest import make_running_worker, make_supervisor
from tests.helpers.task_dir import make_attempt


def _create_events_file(base: Path, task_id: str) -> Path:
    task_dir = base / "tasks" / task_id
    attempt_dir = make_attempt(task_dir, 1)
    events_file = attempt_dir / "events.jsonl"
    events_file.touch()
    return events_file


def _make_supervisor(
    tmp_path: Path,
    log: structlog.BoundLogger | None = None,
    config: RuntimeConfig | None = None,
) -> Supervisor:
    sup = make_supervisor(tmp_path, config=config, services=[], checks=[])
    if log is not None:
        sup.state.log = log
    return sup


# ------ Test 1: Stalled task enters _warned; no duplicate on repeat ------


def test_stalled_task_enters_stall_warned_no_duplicate(tmp_path: Path) -> None:
    log_root = tmp_path / "logs"
    log = setup_supervisor_logger(log_root)
    s = _make_supervisor(
        tmp_path,
        log=log,
        config=RuntimeConfig(stall_warning_minutes=1, stall_action="warn"),
    )
    svc = StallWatch()

    events_file = _create_events_file(tmp_path, "t-stalled")
    old_time = time.time() - 120  # 2 minutes ago
    os.utime(events_file, (old_time, old_time))

    s.state.running["t-stalled"] = make_running_worker("t-stalled", tmp_path)

    asyncio.run(svc.tick(s.state))

    assert "t-stalled" in svc._warned

    # Second call should not change set size
    asyncio.run(svc.tick(s.state))
    assert "t-stalled" in svc._warned
    assert len(svc._warned) == 1
    structlog.reset_defaults()


# ------ Test 2: Refresh mtime removes task; age it again and it returns ------


def test_mtime_refresh_removes_from_stall_warned(tmp_path: Path) -> None:
    s = _make_supervisor(
        tmp_path,
        config=RuntimeConfig(stall_warning_minutes=1, stall_action="warn"),
    )
    svc = StallWatch()

    events_file = _create_events_file(tmp_path, "t-recover")

    s.state.running["t-recover"] = make_running_worker("t-recover", tmp_path)

    # Age it first
    old_time = time.time() - 120
    os.utime(events_file, (old_time, old_time))
    asyncio.run(svc.tick(s.state))
    assert "t-recover" in svc._warned

    # Refresh mtime to now
    os.utime(events_file, None)
    asyncio.run(svc.tick(s.state))
    assert "t-recover" not in svc._warned

    # Age it again -> should return
    os.utime(events_file, (old_time, old_time))
    asyncio.run(svc.tick(s.state))
    assert "t-recover" in svc._warned
    structlog.reset_defaults()


# ------ Test 3: stall_warning_minutes = 0 keeps set empty ------


def test_stall_warning_zero_disables_check(tmp_path: Path) -> None:
    s = _make_supervisor(
        tmp_path,
        config=RuntimeConfig(stall_warning_minutes=0),
    )
    svc = StallWatch()

    events_file = _create_events_file(tmp_path, "t-disabled")
    old_time = time.time() - 600
    os.utime(events_file, (old_time, old_time))

    s.state.running["t-disabled"] = make_running_worker("t-disabled", tmp_path)

    asyncio.run(svc.tick(s.state))
    assert len(svc._warned) == 0
    assert "t-disabled" not in svc._warned
    structlog.reset_defaults()


# ------ Test 4: Missing events.jsonl -> no exception, no entry ------


def test_missing_events_jsonl_no_exception(tmp_path: Path) -> None:
    s = _make_supervisor(
        tmp_path,
        config=RuntimeConfig(stall_warning_minutes=1, stall_action="warn"),
    )
    svc = StallWatch()

    # Create task dir with no events.jsonl
    task_dir = tmp_path / "tasks" / "t-no-events"
    task_dir.mkdir(parents=True)

    s.state.running["t-no-events"] = make_running_worker("t-no-events", tmp_path)

    asyncio.run(svc.tick(s.state))
    assert "t-no-events" not in svc._warned
    assert len(svc._warned) == 0
    structlog.reset_defaults()
