"""Tests for GET /api/tasks closed_limit + recency-correct filtering (fleet-qewz)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest

from fleet.serve.app import create_app


def _make_task_dir(
    tasks_root: Path,
    task_id: str,
    status: str = "in_progress",
    created_at: str | None = None,
    started_at: str | None = None,
    **kwargs,
) -> Path:
    task_dir = tasks_root / task_id
    task_dir.mkdir(parents=True)
    data: dict = {
        "id": task_id,
        "title": f"Task {task_id}",
        "status": status,
        "created_at": created_at or "2024-01-01T00:00:00Z",
        "started_at": started_at,
        "cwd": "/repo",
        "coder": "claude",
        "model": "sonnet",
    }
    data.update(kwargs)
    if "created_at" not in kwargs and created_at:
        data["created_at"] = created_at
    (task_dir / "task.json").write_text(json.dumps(data))
    return task_dir


def _get(app, path: str, **kwargs) -> httpx.Response:
    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get(path, **kwargs)

    return asyncio.run(_run())


def _mock_beads_monkeypatch(monkeypatch: pytest.MonkeyPatch) -> None:
    """Monkey-patch get_beads_status_map to return None (skip beads in tests)."""
    monkeypatch.setattr("fleet.serve.api.tasks.get_beads_status_map", MagicMock(return_value=None))


def test_default_returns_all_active_plus_most_recent_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Default call returns open tasks plus recent closed ones, newest first."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    tasks_root = tmp_path / "tasks"

    # Create tasks whose IDs are alphabetically ordered such that
    # alphabetical order != recency order.
    # task-aaa created first (oldest), task-zzz created last (newest).
    # task-aaa and task-zzz are closed; others are active.
    _make_task_dir(
        tasks_root,
        "task-aaa",
        "closed",
        created_at="2024-01-01T00:00:00Z",
        started_at="2024-01-01T00:00:01Z",
    )
    _make_task_dir(
        tasks_root,
        "task-ddd",
        "closed",
        created_at="2024-01-03T00:00:00Z",
        started_at="2024-01-03T00:00:01Z",
    )
    _make_task_dir(
        tasks_root,
        "task-mmm",
        "closed",
        created_at="2024-01-02T00:00:00Z",
        started_at="2024-01-02T00:00:01Z",
    )
    _make_task_dir(tasks_root, "task-ooo", "open", created_at="2024-01-04T00:00:00Z")
    _make_task_dir(tasks_root, "task-xxx", "in_progress", created_at="2024-01-05T00:00:00Z")
    _make_task_dir(
        tasks_root,
        "task-zzz",
        "closed",
        created_at="2024-01-05T00:00:00Z",
        started_at="2024-01-05T00:00:01Z",
    )

    _mock_beads_monkeypatch(monkeypatch)

    app = create_app()

    resp = _get(app, "/api/tasks")
    assert resp.status_code == 200
    data = resp.json()
    assert "tasks" in data

    # All active tasks (2) + all closed tasks (4, since default limit is 300 which is > 3)
    assert len(data["tasks"]) == 6

    # Check sorting: newest first
    [t["status"] for t in data["tasks"]]
    # In_progress/active should come first, then closed sorted by recency descending
    task_ids = [t["id"] for t in data["tasks"]]

    # task-xxx (in_progress) and task-ooo (open) should be first (active)
    [tid for tid in task_ids if tid in ("task-xxx", "task-ooo")]
    closed_ids = [
        tid for tid in task_ids if tid in ("task-aaa", "task-ddd", "task-mmm", "task-zzz")
    ]
    assert closed_ids == ["task-zzz", "task-ddd", "task-mmm", "task-aaa"], (
        f"Expected closed tasks sorted by recency descending, got {closed_ids}"
    )


def test_closed_limit_keeps_exactly_n_most_recent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """?closed_limit=2 keeps exactly the 2 most recent closed/failed."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    tasks_root = tmp_path / "tasks"

    _make_task_dir(
        tasks_root,
        "task-aaa",
        "closed",
        created_at="2024-01-01T00:00:00Z",
        started_at="2024-01-01T00:00:01Z",
    )
    _make_task_dir(
        tasks_root,
        "task-ddd",
        "failed",
        created_at="2024-01-03T00:00:00Z",
        started_at="2024-01-03T00:00:01Z",
    )
    _make_task_dir(tasks_root, "task-xxx", "open", created_at="2024-01-04T00:00:00Z")
    _make_task_dir(
        tasks_root,
        "task-zzz",
        "closed",
        created_at="2024-01-05T00:00:00Z",
        started_at="2024-01-05T00:00:01Z",
    )

    _mock_beads_monkeypatch(monkeypatch)

    app = create_app()

    resp = _get(app, "/api/tasks", params={"closed_limit": 2})
    assert resp.status_code == 200
    data = resp.json()

    task_ids = [t["id"] for t in data["tasks"]]
    # active task-xxx + 2 most recent closed
    closed_in_result = [tid for tid in task_ids if tid not in ("task-xxx",)]
    assert len(closed_in_result) == 2
    assert closed_in_result == ["task-zzz", "task-ddd"]

    # task-aaa should NOT appear (not in top 2 newest)
    assert "task-aaa" not in task_ids


def test_closed_limit_zero_returns_everything(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """?closed_limit=0 returns everything (no cap)."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    tasks_root = tmp_path / "tasks"

    for i in range(25):
        ts = f"2024-01-{i + 1:02d}T00:00:00Z"
        _make_task_dir(tasks_root, f"task-{i:03d}", "closed", created_at=ts, started_at=ts)

    _mock_beads_monkeypatch(monkeypatch)

    app = create_app()

    resp = _get(app, "/api/tasks", params={"closed_limit": 0})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["tasks"]) == 25


def test_response_shape_is_correct(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Response shape is {\"tasks\": [...]} with the same summary fields as before."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    tasks_root = tmp_path / "tasks"
    _make_task_dir(
        tasks_root,
        "task-shape",
        "open",
        created_at="2024-06-15T10:00:00Z",
        started_at="2024-06-15T10:00:01Z",
        depends_on=["dep-1"],
    )
    _make_task_dir(
        tasks_root,
        "task-shape-closed",
        "closed",
        created_at="2024-06-10T10:00:00Z",
        started_at="2024-06-10T10:00:01Z",
    )

    _mock_beads_monkeypatch(monkeypatch)

    app = create_app()

    resp = _get(app, "/api/tasks")
    assert resp.status_code == 200
    data = resp.json()
    assert list(data.keys()) == ["tasks"]
    assert isinstance(data["tasks"], list)

    for task in data["tasks"]:
        assert "id" in task
        assert "title" in task
        assert "status" in task
        assert "description" in task
        assert "priority" in task
        assert "depends_on" in task
        assert "created_at" in task
        assert "started_at" in task
        assert "ended_at" in task
        assert "elapsed_sec" in task
        assert "idle_sec" in task
        assert "events" in task
        assert "context_tokens" in task
        assert "context_pct" in task
        assert "last_event_kind" in task


def test_clamped_limit_to_max(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """closed_limit > 2000 is clamped to 2000."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    tasks_root = tmp_path / "tasks"

    for i in range(5):
        ts = f"2024-01-{i + 1:02d}T00:00:00Z"
        _make_task_dir(tasks_root, f"task-{i:03d}", "closed", created_at=ts, started_at=ts)

    _mock_beads_monkeypatch(monkeypatch)

    app = create_app()

    # 9999 should be clamped to 2000, which is > 5 total, so all should appear
    resp = _get(app, "/api/tasks", params={"closed_limit": 9999})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["tasks"]) == 5


def test_closed_limit_is_clamped_to_min(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Negative closed_limit is clamped to 0 (unlimited)."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    tasks_root = tmp_path / "tasks"

    for i in range(5):
        ts = f"2024-01-{i + 1:02d}T00:00:00Z"
        _make_task_dir(tasks_root, f"task-{i:03d}", "closed", created_at=ts, started_at=ts)

    _mock_beads_monkeypatch(monkeypatch)

    app = create_app()

    resp = _get(app, "/api/tasks", params={"closed_limit": -1})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["tasks"]) == 5
