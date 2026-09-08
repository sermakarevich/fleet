"""Tests for `state.task_meta.TaskMeta`, the one owner of task.json."""

from __future__ import annotations

import json
from pathlib import Path

from fleet.state.task_meta import TaskMeta


def _task_dir(tmp_path: Path) -> Path:
    task_dir = tmp_path / "tasks" / "t-001"
    task_dir.mkdir(parents=True)
    return task_dir


def test_load_returns_none_when_missing(tmp_path: Path) -> None:
    assert TaskMeta.load(_task_dir(tmp_path)) is None


def test_update_creates_and_save_round_trips(tmp_path: Path) -> None:
    task_dir = _task_dir(tmp_path)
    meta = TaskMeta.update(task_dir, title="hello", status="open", cwd="/repo", custom="kept")
    assert meta.title == "hello"
    assert meta.extra["custom"] == "kept"
    raw = json.loads((task_dir / "task.json").read_text(encoding="utf-8"))
    assert raw["title"] == "hello"
    assert raw["custom"] == "kept"
    assert TaskMeta.load(task_dir) == meta


def test_update_preserves_unknown_fields(tmp_path: Path) -> None:
    task_dir = _task_dir(tmp_path)
    (task_dir / "task.json").write_text(
        json.dumps({"id": "t-001", "priority": 3, "retry_after": "later"}), encoding="utf-8"
    )
    TaskMeta.update(task_dir, coder="claude", model="sonnet")
    raw = json.loads((task_dir / "task.json").read_text(encoding="utf-8"))
    assert raw["priority"] == 3
    assert raw["retry_after"] == "later"
    assert raw["coder"] == "claude"


def test_clear_drops_extra_keys_and_resets_named_fields(tmp_path: Path) -> None:
    task_dir = _task_dir(tmp_path)
    TaskMeta.update(task_dir, status="blocked", blocked_reason="x", retry_after="soon")
    TaskMeta.clear(task_dir, "retry_after", "blocked_reason")
    raw = json.loads((task_dir / "task.json").read_text(encoding="utf-8"))
    assert "retry_after" not in raw
    assert "blocked_reason" not in raw
    assert raw["status"] == "blocked"


def test_from_dict_splits_known_and_extra() -> None:
    meta = TaskMeta.from_dict("t-9", {"id": "t-9", "cwd": "/x", "job_gate": "off"})
    assert meta.cwd == "/x"
    assert meta.extra == {"job_gate": "off"}
    assert meta.to_dict() == {"id": "t-9", "cwd": "/x", "job_gate": "off"}


def test_clear_removes_keys_entirely(tmp_path: Path) -> None:
    task_dir = _task_dir(tmp_path)
    TaskMeta.update(task_dir, status="blocked", blocked_reason="x", blocked_at="then")
    TaskMeta.clear(task_dir, "blocked_reason", "blocked_at")
    raw = json.loads((task_dir / "task.json").read_text(encoding="utf-8"))
    assert "blocked_reason" not in raw
    assert "blocked_at" not in raw
    assert raw["status"] == "blocked"
