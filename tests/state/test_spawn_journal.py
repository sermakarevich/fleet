"""Tests for fleet.state.spawn_journal: is a job's spawn phase finished?"""

from __future__ import annotations

import json
from pathlib import Path

from fleet.state.spawn_journal import spawn_complete


def _write(task_dir: Path, name: str, doc: object) -> None:
    artifacts = task_dir / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    (artifacts / name).write_text(json.dumps(doc), encoding="utf-8")


def test_no_tasks_json_counts_as_complete(tmp_path: Path) -> None:
    assert spawn_complete(tmp_path) is True


def test_partial_journal_is_incomplete(tmp_path: Path) -> None:
    _write(tmp_path, "tasks.json", {"tasks": [{"key": "a"}, {"key": "b"}]})
    _write(tmp_path, "children.json", {"a": "kid-1"})
    assert spawn_complete(tmp_path) is False


def test_full_journal_is_complete(tmp_path: Path) -> None:
    _write(tmp_path, "tasks.json", {"tasks": [{"key": "a"}, {"key": "b"}]})
    _write(tmp_path, "children.json", {"a": "kid-1", "b": "kid-2"})
    assert spawn_complete(tmp_path) is True


def test_skipped_keys_count_as_journaled(tmp_path: Path) -> None:
    _write(tmp_path, "tasks.json", {"tasks": [{"key": "a"}, {"key": "b"}]})
    _write(tmp_path, "children.json", {"a": "kid-1"})
    _write(tmp_path, "children_skipped.json", {"b": "builder failed"})
    assert spawn_complete(tmp_path) is True


def test_empty_journal_falls_back_to_complete(tmp_path: Path) -> None:
    """Children made outside SpawnChildren (observer follow-ups) keep the old path."""
    _write(tmp_path, "tasks.json", {"tasks": [{"key": "a"}]})
    assert spawn_complete(tmp_path) is True


def test_corrupt_files_do_not_raise(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    (artifacts / "tasks.json").write_text("{not json", encoding="utf-8")
    assert spawn_complete(tmp_path) is True
