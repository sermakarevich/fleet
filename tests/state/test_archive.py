"""Tests for `fleet gc` (archive closed task dirs older than N days)."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from fleet.cli.main import app
from fleet.state.archive import find_stale_worktrees, gc_tasks, purge_archive

runner = CliRunner()

OLD = time.time() - 40 * 86400


def _make_task(home: Path, task_id: str, status: str, old: bool) -> Path:
    d = home / "tasks" / task_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "task.json").write_text(json.dumps({"id": task_id, "status": status}), encoding="utf-8")
    (d / "data.txt").write_text("payload", encoding="utf-8")
    mtime = OLD if old else time.time()
    os.utime(d, (mtime, mtime))
    return d


def test_gc_moves_closed_old(tmp_path: Path) -> None:
    _make_task(tmp_path, "fleet-old", "closed", old=True)
    result = gc_tasks(tmp_path, days=30)
    assert result.archived == ["fleet-old"]
    assert (tmp_path / "archive" / "tasks" / "fleet-old").is_dir()
    assert not (tmp_path / "tasks" / "fleet-old").exists()


def test_gc_skips_closed_recent(tmp_path: Path) -> None:
    _make_task(tmp_path, "fleet-recent", "closed", old=False)
    result = gc_tasks(tmp_path, days=30)
    assert result.archived == []
    assert result.skipped == 1
    assert (tmp_path / "tasks" / "fleet-recent").is_dir()


def test_gc_skips_open_old(tmp_path: Path) -> None:
    _make_task(tmp_path, "fleet-open", "in_progress", old=True)
    result = gc_tasks(tmp_path, days=30)
    assert result.archived == []
    assert result.skipped == 1
    assert (tmp_path / "tasks" / "fleet-open").is_dir()


def test_gc_dry_run_moves_nothing(tmp_path: Path) -> None:
    _make_task(tmp_path, "fleet-dry", "closed", old=True)
    result = gc_tasks(tmp_path, days=30, dry_run=True)
    assert result.archived == ["fleet-dry"]
    assert (tmp_path / "tasks" / "fleet-dry").is_dir()
    assert not (tmp_path / "archive" / "tasks" / "fleet-dry").exists()


def test_gc_cli_reports_archived(tmp_path: Path) -> None:
    _make_task(tmp_path, "fleet-cli", "closed", old=True)
    with patch("fleet.cli.bootstrap.home", return_value=tmp_path):
        result = runner.invoke(app, ["gc", "--days", "30"])
    assert result.exit_code == 0, result.output
    assert "archived" in result.output


def test_gc_days_zero_disables(tmp_path: Path) -> None:
    _make_task(tmp_path, "fleet-old", "closed", old=True)
    result = gc_tasks(tmp_path, days=0)
    assert result.archived == []
    assert (tmp_path / "tasks" / "fleet-old").is_dir()


def _make_archive(home: Path, name: str, old: bool, age_days: int = 40) -> Path:
    d = home / "archive" / "tasks" / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "data.txt").write_text("payload", encoding="utf-8")
    mtime = time.time() - age_days * 86400 if old else time.time()
    os.utime(d, (mtime, mtime))
    return d


def test_purge_deletes_old_archives(tmp_path: Path) -> None:
    _make_archive(tmp_path, "fleet-gone", old=True, age_days=100)
    result = purge_archive(tmp_path, days=90)
    assert result.deleted == ["fleet-gone"]
    assert result.bytes_freed > 0
    assert not (tmp_path / "archive" / "tasks" / "fleet-gone").exists()


def test_purge_skips_recent_archives(tmp_path: Path) -> None:
    _make_archive(tmp_path, "fleet-fresh", old=False)
    result = purge_archive(tmp_path, days=90)
    assert result.deleted == []
    assert result.skipped == 1
    assert (tmp_path / "archive" / "tasks" / "fleet-fresh").is_dir()


def test_purge_dry_run_and_disabled(tmp_path: Path) -> None:
    _make_archive(tmp_path, "fleet-dry", old=True, age_days=100)
    result = purge_archive(tmp_path, days=90, dry_run=True)
    assert result.deleted == ["fleet-dry"]
    assert (tmp_path / "archive" / "tasks" / "fleet-dry").is_dir()
    result = purge_archive(tmp_path, days=0)
    assert result.deleted == []


def _make_worktree(home: Path, name: str) -> Path:
    d = home / "worktrees" / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "file.txt").write_text("work", encoding="utf-8")
    return d


def test_find_stale_worktrees(tmp_path: Path) -> None:
    _make_task(tmp_path, "fleet-old", "closed", old=True)
    _make_task(tmp_path, "fleet-open", "in_progress", old=True)
    wt_old = _make_worktree(tmp_path, "myrepo-fleet-old")
    _make_worktree(tmp_path, "myrepo-fleet-open")
    _make_worktree(tmp_path, "myrepo-fleet-unknown")
    stale = find_stale_worktrees(tmp_path, days=30)
    assert [(s.task_id, s.path) for s in stale] == [("fleet-old", wt_old)]


def test_find_stale_worktrees_disabled(tmp_path: Path) -> None:
    _make_task(tmp_path, "fleet-old", "closed", old=True)
    _make_worktree(tmp_path, "fleet-old")
    assert find_stale_worktrees(tmp_path, days=0) == []


def test_gc_cli_purge_flag(tmp_path: Path) -> None:
    _make_archive(tmp_path, "fleet-purge-me", old=True, age_days=100)
    with patch("fleet.cli.bootstrap.home", return_value=tmp_path):
        result = runner.invoke(app, ["gc", "--days", "30", "--purge"])
    assert result.exit_code == 0, result.output
    assert "purged 1" in result.output
    assert not (tmp_path / "archive" / "tasks" / "fleet-purge-me").exists()
