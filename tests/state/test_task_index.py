"""Tests for state/task_index.py — the one walker of tasks/*."""

from __future__ import annotations

import json
from pathlib import Path

from fleet.state.task_index import TaskIndex


def _write_task(tasks_root: Path, task_id: str, data: dict | None = None) -> Path:
    task_dir = tasks_root / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    body = {"id": task_id, "title": f"Task {task_id}", "status": "open"}
    body.update(data or {})
    (task_dir / "task.json").write_text(json.dumps(body))
    return task_dir


def test_list_ids_sorted_and_skips_bare_dirs(tmp_path: Path) -> None:
    """list_ids returns sorted ids, skipping dirs without task.json."""
    tasks_root = tmp_path / "tasks"
    _write_task(tasks_root, "b-task")
    _write_task(tasks_root, "a-task")
    (tasks_root / "bare-dir").mkdir(parents=True)

    assert TaskIndex(tmp_path).list_ids() == ["a-task", "b-task"]


def test_list_ids_empty_when_no_tasks_dir(tmp_path: Path) -> None:
    """Missing tasks/ reads as empty, never raises."""
    assert TaskIndex(tmp_path).list_ids() == []


def test_iter_meta_yields_dirs_and_raw_dicts(tmp_path: Path) -> None:
    """iter_meta pairs each task dir with its raw task.json dict."""
    tasks_root = tmp_path / "tasks"
    _write_task(tasks_root, "t1", {"status": "in_progress"})

    rows = list(TaskIndex(tmp_path).iter_meta())
    assert len(rows) == 1
    task_dir, raw = rows[0]
    assert task_dir.name == "t1"
    assert raw["status"] == "in_progress"


def test_iter_meta_skips_unparseable_task_json(tmp_path: Path) -> None:
    """Broken task.json files are skipped, not raised."""
    tasks_root = tmp_path / "tasks"
    _write_task(tasks_root, "good")
    bad = tasks_root / "bad"
    bad.mkdir(parents=True)
    (bad / "task.json").write_text("{not json")

    assert [d.name for d, _ in TaskIndex(tmp_path).iter_meta()] == ["good"]


def test_find_returns_dir_or_none(tmp_path: Path) -> None:
    """find resolves the task dir; None when task.json is missing."""
    tasks_root = tmp_path / "tasks"
    _write_task(tasks_root, "t1")
    index = TaskIndex(tmp_path)

    assert index.find("t1") == tasks_root / "t1"
    assert index.find("nope") is None


def test_read_raw_caches_by_mtime(tmp_path: Path) -> None:
    """Second read avoids disk; an edit invalidates the cache."""
    tasks_root = tmp_path / "tasks"
    task_dir = _write_task(tasks_root, "t1", {"status": "open"})
    index = TaskIndex(tmp_path)

    assert index.read_raw("t1")["status"] == "open"
    (task_dir / "task.json").write_text(json.dumps({"id": "t1", "status": "closed"}))
    assert index.read_raw("t1")["status"] == "closed"


def test_status_and_load_meta(tmp_path: Path) -> None:
    """status reads the cached field; load_meta returns the typed view."""
    tasks_root = tmp_path / "tasks"
    _write_task(tasks_root, "t1", {"status": "blocked"})
    index = TaskIndex(tmp_path)

    assert index.status("t1") == "blocked"
    assert index.status("nope") is None
    meta = index.load_meta("t1")
    assert meta is not None and meta.id == "t1" and meta.status == "blocked"
    assert index.load_meta("nope") is None
