"""Shared fixtures and helpers for serve tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from fleet.serve.analytics import records as records_mod
from fleet.state import runtime_stats as stats_mod

# ---------------------------------------------------------------------------
# Shared by test_routes.py splits (Clean 29/30: moved, not rewritten).
# ---------------------------------------------------------------------------


def _make_task_dir(
    tasks_root: Path,
    task_id: str,
    status: str = "in_progress",
    **kwargs,
) -> Path:
    task_dir = tasks_root / task_id
    task_dir.mkdir(parents=True)
    data: dict = {
        "id": task_id,
        "title": f"Task {task_id}",
        "status": status,
        "cwd": "/repo",
        "coder": "claude",
        "model": "sonnet",
    }
    data.update(kwargs)
    (task_dir / "task.json").write_text(json.dumps(data))
    return task_dir


def _make_attempt_dir(tmp_path: Path, task_id: str = "task-attempt") -> Path:
    task_dir = _make_task_dir(tmp_path / "tasks", task_id)
    attempt_dir = task_dir / "attempts" / "1"
    attempt_dir.mkdir(parents=True)
    (attempt_dir / "run.json").write_text(
        json.dumps({"launch": {"mode": "continue", "pack_bytes": 7, "kind": "work"}})
    )
    (attempt_dir / "prompt.md").write_text("the rendered prompt")
    (attempt_dir / "STATE.md").write_text("## Next\ndo the thing")
    (attempt_dir / "RESULT.json").write_text(
        json.dumps({"schema": 1, "status": "partial", "summary": "wip"})
    )
    (task_dir / "attempts.jsonl").write_text(
        json.dumps(
            {
                "event": "start",
                "n": 1,
                "ts": "2026-01-01T00:00:00+00:00",
                "coder": "claude",
                "model": "sonnet",
                "worker": "task.continue",
            }
        )
        + "\n"
    )
    return task_dir


# ---------------------------------------------------------------------------
# Shared by test_analytics_summary.py splits (Clean 29/30: moved, not rewritten).
# ---------------------------------------------------------------------------


def _patch_no_beads(monkeypatch: pytest.MonkeyPatch) -> None:
    """Monkey-patch get_beads_status_map to return None (bd unavailable in tests)."""
    monkeypatch.setattr(
        "fleet.beads.status_cache.get_beads_status_map",
        MagicMock(return_value=None),
    )


def _reset_analytics_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clear the owner-held EventScanCache objects that persist across tests."""

    records_mod._events_cache.clear()
    stats_mod._events_cache.clear()


def make_task_dir(
    tasks_root: Path,
    task_id: str,
    *,
    status: str = "in_progress",
    coder: str = "claude",
    model: str = "sonnet",
    cwd: str = "/repo",
    priority: int = 1,
    created_at: str | None = None,
    status_raw: str | None = None,
) -> Path:
    """Create a task directory with task.json and events."""
    td = tasks_root / task_id
    td.mkdir(parents=True)
    data: dict = {
        "id": task_id,
        "title": f"Task {task_id}",
        "status": status_raw or status,
        "cwd": cwd,
        "coder": coder,
        "model": model,
        "priority": priority,
    }
    if created_at is not None:
        data["created_at"] = created_at
    (td / "task.json").write_text(json.dumps(data), "utf-8")
    return td


def write_events(td: Path, lines: list[str]) -> None:
    """Write event lines to attempts/1/events.jsonl."""
    attempt_dir = td / "attempts" / "1"
    attempt_dir.mkdir(parents=True, exist_ok=True)
    (attempt_dir / "events.jsonl").write_text("\n".join(lines) + "\n", "utf-8")


def ev(
    ts: str = "2025-06-01T10:00:00Z",
    kind: str = "session_started",
    session_id: str | None = None,
    **kwargs,
) -> str:
    r: dict = {"ts": ts, "kind": kind}
    if session_id:
        r["session_id"] = session_id
    r.update(kwargs)
    return json.dumps(r)


def _make_future_days(n_days: int) -> str:
    """Return an ISO timestamp n days ago now."""
    return (datetime.now(tz=UTC) - timedelta(days=n_days)).isoformat()


def _make_window_day(hours_ago: int = 6) -> str:
    """Return a timestamp hours_ago ago — comfortably within any 1–7 day window."""
    return (datetime.now(tz=UTC) - timedelta(hours=hours_ago)).isoformat()
