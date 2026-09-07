from __future__ import annotations

import os
import time
from pathlib import Path

import structlog

from fleet.core.config import RuntimeConfig
from fleet.logging import setup_supervisor_logger

from tests.orchestrator.test_supervisor_status_log import _make_supervisor


def _create_events_file(base: Path, task_id: str) -> Path:
    task_dir = base / "tasks" / task_id
    task_dir.mkdir(parents=True)
    events_file = task_dir / "events.jsonl"
    events_file.touch()
    return events_file


# ------ Test 1: Stalled task enters _stall_warned; no duplicate on repeat ------


def test_stalled_task_enters_stall_warned_no_duplicate(tmp_path: Path) -> None:
    log_root = tmp_path / "logs"
    log = setup_supervisor_logger(log_root)
    s = _make_supervisor(
        tmp_path,
        log=log,
        config=RuntimeConfig(stall_warning_minutes=1),
    )

    events_file = _create_events_file(tmp_path, "t-stalled")
    old_time = time.time() - 120  # 2 minutes ago
    os.utime(events_file, (old_time, old_time))

    s.in_flight["t-stalled"] = object()

    s._log_status_snapshot()

    assert "t-stalled" in s._stall_warned

    # Second call should not change set size
    s._log_status_snapshot()
    assert "t-stalled" in s._stall_warned
    assert len(s._stall_warned) == 1
    structlog.reset_defaults()


# ------ Test 2: Refresh mtime removes task; age it again and it returns ------


def test_mtime_refresh_removes_from_stall_warned(tmp_path: Path) -> None:
    s = _make_supervisor(
        tmp_path,
        config=RuntimeConfig(stall_warning_minutes=1),
    )

    events_file = _create_events_file(tmp_path, "t-recover")

    s.in_flight["t-recover"] = object()

    # Age it first
    old_time = time.time() - 120
    os.utime(events_file, (old_time, old_time))
    s._log_status_snapshot()
    assert "t-recover" in s._stall_warned

    # Refresh mtime to now
    os.utime(events_file, None)
    s._log_status_snapshot()
    assert "t-recover" not in s._stall_warned

    # Age it again -> should return
    os.utime(events_file, (old_time, old_time))
    s._log_status_snapshot()
    assert "t-recover" in s._stall_warned
    structlog.reset_defaults()


# ------ Test 3: stall_warning_minutes = 0 keeps set empty ------


def test_stall_warning_zero_disables_check(tmp_path: Path) -> None:
    s = _make_supervisor(
        tmp_path,
        config=RuntimeConfig(stall_warning_minutes=0),
    )

    events_file = _create_events_file(tmp_path, "t-disabled")
    old_time = time.time() - 600
    os.utime(events_file, (old_time, old_time))

    s.in_flight["t-disabled"] = object()

    s._log_status_snapshot()
    assert len(s._stall_warned) == 0
    assert "t-disabled" not in s._stall_warned
    structlog.reset_defaults()


# ------ Test 4: Missing events.jsonl -> no exception, no entry ------


def test_missing_events_jsonl_no_exception(tmp_path: Path) -> None:
    s = _make_supervisor(
        tmp_path,
        config=RuntimeConfig(stall_warning_minutes=1),
    )

    # Create task dir with no events.jsonl
    task_dir = tmp_path / "tasks" / "t-no-events"
    task_dir.mkdir(parents=True)

    s.in_flight["t-no-events"] = object()

    s._log_status_snapshot()
    assert "t-no-events" not in s._stall_warned
    assert len(s._stall_warned) == 0
    structlog.reset_defaults()
