"""Tests for orchestrator/retention_gc.py: on_start and tick run retention passes."""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path

from fleet.core.limits import GC_INTERVAL_SEC
from fleet.orchestrator.retention_gc import (
    make_retention_gc,
    retention_gc_on_start,
    retention_gc_pass,
    retention_gc_tick,
)
from tests.conftest import make_supervisor

OLD = time.time() - 40 * 86400


def _make_task(fleet_home: Path, task_id: str, status: str, old: bool) -> Path:
    d = fleet_home / "tasks" / task_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "task.json").write_text(json.dumps({"id": task_id, "status": status}), encoding="utf-8")
    mtime = OLD if old else time.time()
    os.utime(d, (mtime, mtime))
    return d


def _home_with_old_task(tmp_path: Path, task_id: str) -> Path:
    fleet_home = tmp_path / ".fleet"
    (fleet_home / "tasks").mkdir(parents=True)
    _make_task(fleet_home, task_id, "closed", old=True)
    wt = fleet_home / "worktrees" / f"myrepo-{task_id}"
    wt.mkdir(parents=True)
    (wt / "file.txt").write_text("work", encoding="utf-8")
    return fleet_home


def _sup_for(fleet_home: Path, tmp_path: Path):
    sup = make_supervisor(tmp_path, services=[], checks=[])
    sup.state.fleet_home = fleet_home
    return sup


def test_on_start_runs_one_pass(tmp_path: Path) -> None:
    """on_start archives the old closed task and drops its stale worktree."""
    fleet_home = _home_with_old_task(tmp_path, "fleet-old")
    sup = _sup_for(fleet_home, tmp_path)

    asyncio.run(retention_gc_on_start(sup.state))

    assert (fleet_home / "archive" / "tasks" / "fleet-old").is_dir()
    assert not (fleet_home / "tasks" / "fleet-old").exists()
    assert not (fleet_home / "worktrees" / "myrepo-fleet-old").exists()


def test_tick_runs_another_pass(tmp_path: Path) -> None:
    """tick runs a retention pass just like on_start does."""
    fleet_home = _home_with_old_task(tmp_path, "fleet-old-tick")
    sup = _sup_for(fleet_home, tmp_path)

    asyncio.run(retention_gc_tick(sup.state))

    assert (fleet_home / "archive" / "tasks" / "fleet-old-tick").is_dir()
    assert not (fleet_home / "tasks" / "fleet-old-tick").exists()


def test_disabled_config_skips_everything(tmp_path: Path) -> None:
    """gc_retention_days=0 and gc_archive_days=0 leave everything in place."""
    fleet_home = tmp_path / ".fleet"
    (fleet_home / "tasks").mkdir(parents=True)
    _make_task(fleet_home, "fleet-old", "closed", old=True)
    wt = fleet_home / "worktrees" / "fleet-old"
    wt.mkdir(parents=True)

    sup = _sup_for(fleet_home, tmp_path)
    sup.state.config.gc_retention_days = 0
    sup.state.config.gc_archive_days = 0
    retention_gc_pass(sup.state)

    assert (fleet_home / "tasks" / "fleet-old").is_dir()
    assert wt.is_dir()


def test_default_interval_matches_limits() -> None:
    """Default interval comes from core/limits.py; ctor arg overrides it."""
    assert make_retention_gc().interval_sec == GC_INTERVAL_SEC
    assert make_retention_gc(interval_sec=0.01).interval_sec == 0.01
