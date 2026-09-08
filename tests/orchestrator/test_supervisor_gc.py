"""Tests for `Supervisor._run_retention_gc` (scheduled retention pass)."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import structlog

from fleet.orchestrator.supervisor import Supervisor

OLD = time.time() - 40 * 86400


class StubQueue:
    def claim_next(self, claimer_id):
        return None

    def release(self, task_id, reason="", wait_sec=0):
        pass

    def set_blocked(self, task_id, reason=""):
        pass

    def close(self, task_id, reason="completed"):
        pass

    def comment(self, task_id, body):
        pass

    def get(self, task_id):
        pass

    def list_ready(self, limit=50):
        return []

    def list_in_progress(self, limit=500):
        return []


class StubCoder:
    name = "stub"

    def build_argv(self, task, artifact_dir, plan=None):
        return ["echo"]

    def env(self, task, artifact_dir):
        return {}

    def normalize_event(self, raw_line):
        return None


def _make_supervisor(home: Path) -> Supervisor:
    return Supervisor(
        coder=StubCoder(),
        queue=StubQueue(),
        runtime_toml_path=home / "runtime.toml",
        project_root=home,
        log=structlog.get_logger(),
    )


def _make_task(home: Path, task_id: str, status: str, old: bool) -> Path:
    d = home / "tasks" / task_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "task.json").write_text(
        json.dumps({"id": task_id, "status": status}), encoding="utf-8"
    )
    mtime = OLD if old else time.time()
    os.utime(d, (mtime, mtime))
    return d


def test_retention_gc_archives_and_cleans_worktree(tmp_path: Path) -> None:
    home = tmp_path / ".fleet"
    (home / "tasks").mkdir(parents=True)
    _make_task(home, "fleet-old", "closed", old=True)
    wt = home / "worktrees" / "myrepo-fleet-old"
    wt.mkdir(parents=True)
    (wt / "file.txt").write_text("work", encoding="utf-8")

    sup = _make_supervisor(home)
    sup._run_retention_gc()

    assert (home / "archive" / "tasks" / "fleet-old").is_dir()
    assert not (home / "tasks" / "fleet-old").exists()
    assert not wt.exists()


def test_retention_gc_disabled_skips_everything(tmp_path: Path) -> None:
    home = tmp_path / ".fleet"
    (home / "tasks").mkdir(parents=True)
    _make_task(home, "fleet-old", "closed", old=True)
    wt = home / "worktrees" / "fleet-old"
    wt.mkdir(parents=True)

    sup = _make_supervisor(home)
    sup.config.gc_retention_days = 0
    sup.config.gc_archive_days = 0
    sup._run_retention_gc()

    assert (home / "tasks" / "fleet-old").is_dir()
    assert wt.is_dir()
