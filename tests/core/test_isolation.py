"""Tests for core/isolation.py. Mirrors the source path."""

from __future__ import annotations

import json
from pathlib import Path

from fleet.core.isolation import IsolationInfo, from_meta, read


def test_from_meta_builds_info() -> None:
    """A complete task.json dict becomes an IsolationInfo."""
    info = from_meta({"repo_root": "/r", "base_ref": "main", "worktree_path": "/w"})
    assert info == IsolationInfo(repo_root="/r", base_ref="main", worktree_path="/w")


def test_from_meta_rejects_partials() -> None:
    """Missing keys, non-dicts, and empties all read as not isolated."""
    assert from_meta({"repo_root": "/r", "base_ref": "main"}) is None
    assert from_meta({}) is None


def test_read_prefers_task_json(tmp_path: Path) -> None:
    """task.json isolation info wins over the legacy marker."""
    task_dir = tmp_path / "t-1"
    task_dir.mkdir()
    (task_dir / "task.json").write_text(
        json.dumps({"repo_root": "/r", "base_ref": "dev", "worktree_path": "/w"}),
        encoding="utf-8",
    )
    (task_dir / ".worktree").write_text("/legacy\n", encoding="utf-8")
    assert read(task_dir) == IsolationInfo(repo_root="/r", base_ref="dev", worktree_path="/w")


def test_read_falls_back_to_legacy_marker(tmp_path: Path) -> None:
    """Old task dirs with only a .worktree marker still resolve."""
    task_dir = tmp_path / "t-2"
    task_dir.mkdir()
    (task_dir / "task.json").write_text(json.dumps({"id": "t-2"}), encoding="utf-8")
    (task_dir / ".worktree").write_text("/legacy-wt\n", encoding="utf-8")
    assert read(task_dir) == IsolationInfo(
        repo_root="", base_ref="main", worktree_path="/legacy-wt"
    )


def test_read_returns_none_when_missing_or_broken(tmp_path: Path) -> None:
    """Absent dirs, absent files, and bad JSON all read as not isolated."""
    assert read(tmp_path / "nope") is None
    task_dir = tmp_path / "t-3"
    task_dir.mkdir()
    assert read(task_dir) is None
    (task_dir / "task.json").write_text("{not json", encoding="utf-8")
    assert read(task_dir) is None
