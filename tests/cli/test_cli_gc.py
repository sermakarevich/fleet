"""Tests for `fleet gc` (archive closed task dirs older than N days)."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from fleet.cli.main import app
from fleet.gc import gc_tasks

runner = CliRunner()

OLD = time.time() - 40 * 86400


def _make_task(home: Path, task_id: str, status: str, old: bool) -> Path:
    d = home / "tasks" / task_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "task.json").write_text(
        json.dumps({"id": task_id, "status": status}), encoding="utf-8"
    )
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
    with patch("fleet.cli.tasks.fleet_home", return_value=tmp_path):
        result = runner.invoke(app, ["gc", "--days", "30"])
    assert result.exit_code == 0, result.output
    assert "archived" in result.output
