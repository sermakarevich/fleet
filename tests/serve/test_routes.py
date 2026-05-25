"""Tests for REST API routes (FR-07, FR-31, FR-32, FR-33, FR-34, FR-35, FR-36, FR-37, FR-38, FR-39, FR-40, FR-41, FR-42, FR-43, FR-44)."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest

from fleet.queue import BeadsQueue
from fleet.schemas import Task
from fleet.serve.app import create_app


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


def test_tasks_list_returns_tasks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /api/tasks returns task list with correct shape (FR-07)."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    tasks_root = tmp_path / "tasks"
    _make_task_dir(tasks_root, "task-abc", "in_progress")

    app = create_app()

    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get("/api/tasks")

    resp = asyncio.run(_run())
    assert resp.status_code == 200
    data = resp.json()
    assert "tasks" in data
    assert len(data["tasks"]) == 1
    t = data["tasks"][0]
    assert t["id"] == "task-abc"
    assert t["title"] == "Task task-abc"
    assert t["status"] == "in_progress"
    assert "elapsed_sec" in t
    assert "events" in t


def test_task_kill_200(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """POST /api/tasks/{id}/kill calls queue.release and returns 200 (FR-07)."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    tasks_root = tmp_path / "tasks"
    _make_task_dir(tasks_root, "task-kill", "in_progress")
    mock_queue = MagicMock(spec=BeadsQueue)
    app = create_app(queue=mock_queue)

    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.post("/api/tasks/task-kill/kill")

    resp = asyncio.run(_run())
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    mock_queue.release.assert_called_once_with("task-kill")


def test_task_kill_404(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """POST /api/tasks/{id}/kill returns 404 for unknown task (FR-07)."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    app = create_app()

    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.post("/api/tasks/nonexistent/kill")

    resp = asyncio.run(_run())
    assert resp.status_code == 404


def test_config_get_returns_fields(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /api/config returns all RuntimeConfig fields (FR-43)."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    app = create_app()

    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get("/api/config")

    resp = asyncio.run(_run())
    assert resp.status_code == 200
    data = resp.json()
    assert "max_concurrent" in data
    assert "model" in data
    assert "coder" in data
    assert "context_pressure_threshold_pct" in data


def test_config_put_updates_field(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """PUT /api/config updates runtime.toml atomically and returns new config (FR-43)."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    app = create_app()

    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.put("/api/config", json={"max_concurrent": "5"})

    resp = asyncio.run(_run())
    assert resp.status_code == 200
    data = resp.json()
    assert data["max_concurrent"] == 5
    assert (tmp_path / "runtime.toml").exists()


def test_analytics_throughput_shape(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /api/analytics/throughput returns buckets list with correct keys (FR-35, FR-36)."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    app = create_app()

    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get("/api/analytics/throughput")

    resp = asyncio.run(_run())
    assert resp.status_code == 200
    data = resp.json()
    assert "buckets" in data
    assert isinstance(data["buckets"], list)
    if data["buckets"]:
        b = data["buckets"][0]
        assert "hour" in b
        assert "success" in b
        assert "failure" in b
        assert "rate_limit" in b
        assert "context_pressure" in b
        assert "blocked_by_agent" in b
