"""Tests for state.runtime_stats (moved from serve/stats)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fleet.state.runtime_stats import (
    task_files_touched_from_dir,
    task_runtime_info_cached,
    task_runtime_stats,
    task_runtime_stats_from_dir,
)
from tests.helpers.task_dir import make_attempt


def _seed_events(attempt_dir: Path) -> None:
    (attempt_dir / "events.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "kind": "assistant_text",
                        "ts": "2026-06-12T10:00:00+00:00",
                        "usage": {"input_tokens": 1000},
                        "raw": {},
                    }
                ),
                json.dumps(
                    {
                        "kind": "tool_use",
                        "ts": "2026-06-12T10:01:00+00:00",
                        "tool_name": "Read",
                        "usage": None,
                        "raw": {"input": {"file_path": "/a.py"}},
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (attempt_dir / "log.jsonl").write_text(
        json.dumps({"event": "subprocess_started", "timestamp": "2026-06-12T10:00:00Z"}) + "\n",
        encoding="utf-8",
    )


def test_stats_from_dir_reads_events_and_start(tmp_path: Path) -> None:
    task_dir = tmp_path / "tasks" / "t-stats"
    attempt_dir = make_attempt(task_dir, 1)
    _seed_events(attempt_dir)

    stats = task_runtime_stats_from_dir(task_dir)

    assert stats.events == 2
    assert stats.context_tokens == 1000
    assert stats.started_at is not None
    assert stats.last_event_at is not None


def test_info_cached_includes_last_event_fields(tmp_path: Path) -> None:
    task_dir = tmp_path / "tasks" / "t-info"
    attempt_dir = make_attempt(task_dir, 1)
    _seed_events(attempt_dir)

    info = task_runtime_info_cached(task_dir)

    assert info.events == 2
    assert info.last_event_kind == "tool_use"
    assert info.context_tokens == 1000


def test_stats_missing_dir_is_empty(tmp_path: Path) -> None:
    task_dir = tmp_path / "tasks" / "t-missing"
    task_dir.mkdir(parents=True)

    stats = task_runtime_stats_from_dir(task_dir)

    assert stats.events == 0
    assert stats.started_at is None
    assert stats.context_tokens is None


def test_files_touched_counts_unique_paths(tmp_path: Path) -> None:
    task_dir = tmp_path / "tasks" / "t-files"
    attempt_dir = make_attempt(task_dir, 1)
    _seed_events(attempt_dir)

    assert task_files_touched_from_dir(task_dir) == 1


def test_stats_by_id_uses_fleet_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    task_dir = tmp_path / "tasks" / "t-byid"
    attempt_dir = make_attempt(task_dir, 1)
    _seed_events(attempt_dir)

    stats = task_runtime_stats("t-byid")

    assert stats.events == 2
