"""Tests for state.artifact_locator.locate (CLI-facing artifact paths)."""

from __future__ import annotations

from pathlib import Path

from fleet.state.artifact_locator import locate
from fleet.state.attempts import record_start


def _home_with_attempts(tmp_path: Path, task_id: str, attempts: int = 2) -> Path:
    """Fake fleet home: tasks/<id>/ with *attempts* journaled starts."""
    task_dir = tmp_path / "tasks" / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    for _ in range(attempts):
        n = record_start(task_dir, coder="claude", model="sonnet")
        (task_dir / "attempts" / str(n)).mkdir(parents=True, exist_ok=True)
    return tmp_path


def test_locate_attempt_files_use_latest_start(tmp_path: Path) -> None:
    """log/events/stderr/prompt default to the latest started attempt dir."""
    home = _home_with_attempts(tmp_path, "t-1")
    base = home / "tasks" / "t-1" / "attempts" / "2"
    assert locate(home, "t-1", "log") == base / "log.jsonl"
    assert locate(home, "t-1", "events") == base / "events.jsonl"
    assert locate(home, "t-1", "stderr") == base / "log.stderr"
    assert locate(home, "t-1", "prompt") == base / "prompt.md"


def test_locate_explicit_attempt(tmp_path: Path) -> None:
    """An explicit attempt number wins over the latest start."""
    home = _home_with_attempts(tmp_path, "t-1")
    assert locate(home, "t-1", "events", attempt=1) == (
        home / "tasks" / "t-1" / "attempts" / "1" / "events.jsonl"
    )


def test_locate_empty_journal_points_at_first_slot(tmp_path: Path) -> None:
    """No attempts yet: attempt-scoped artifacts point at attempts/1 (may not exist)."""
    task_dir = tmp_path / "tasks" / "t-new"
    task_dir.mkdir(parents=True, exist_ok=True)
    path = locate(tmp_path, "t-new", "events")
    assert path == task_dir / "attempts" / "1" / "events.jsonl"


def test_locate_state_is_task_level(tmp_path: Path) -> None:
    """STATE.md lives at the task root, independent of attempts."""
    home = _home_with_attempts(tmp_path, "t-1")
    assert locate(home, "t-1", "state") == home / "tasks" / "t-1" / "STATE.md"


def test_locate_result_prefers_live_file(tmp_path: Path) -> None:
    """Live RESULT.json wins when present."""
    home = _home_with_attempts(tmp_path, "t-1")
    live = home / "tasks" / "t-1" / "RESULT.json"
    live.write_text("{}")
    assert locate(home, "t-1", "result") == live


def test_locate_result_falls_back_to_snapshot_then_legacy(tmp_path: Path) -> None:
    """No live file: latest attempt snapshot, else the legacy artifacts path."""
    home = _home_with_attempts(tmp_path, "t-1")
    snapshot = home / "tasks" / "t-1" / "attempts" / "2" / "RESULT.json"
    snapshot.write_text("{}")
    assert locate(home, "t-1", "result") == snapshot
    snapshot.unlink()
    assert locate(home, "t-1", "result") == home / "tasks" / "t-1" / "artifacts" / "RESULT.json"
