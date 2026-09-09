"""Tests for task kill and supervisor routes (unit under test: serve/api tasks/supervisor)."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest

from fleet.serve.app import create_app
from tests.serve.conftest import _make_task_dir


def test_task_kill_killing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """POST /api/tasks/{id}/kill returns killing when the task is in_progress (FR-07)."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    tasks_root = tmp_path / "tasks"
    task_dir = _make_task_dir(tasks_root, "task-kill", "in_progress")
    # Write supervisor PID file pointing at the live test process.
    (tmp_path / ".supervisor.pid").write_text(json.dumps({"pid": os.getpid()}))
    app = create_app()

    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.post("/api/tasks/task-kill/kill")

    resp = asyncio.run(_run())
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "result": "killing"}
    assert (task_dir / ".kill").exists(), ".kill sentinel should be written"


def test_task_kill_supervisor_not_running(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """POST /api/tasks/{id}/kill returns supervisor-not-running when no live supervisor (FR-07)."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    tasks_root = tmp_path / "tasks"
    task_dir = _make_task_dir(tasks_root, "task-kill-sv", "in_progress")
    # No .supervisor.pid file — supervisor is not running.
    app = create_app()

    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.post("/api/tasks/task-kill-sv/kill")

    resp = asyncio.run(_run())
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "result": "supervisor-not-running"}
    assert (task_dir / ".kill").exists(), ".kill sentinel should still be written"


def test_task_kill_queued_closes_immediately(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """POST /api/tasks/{id}/kill closes queued tasks via queue.close, writes no sentinel (FR-07)."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    tasks_root = tmp_path / "tasks"
    task_dir = _make_task_dir(tasks_root, "task-kill-nr", "open")
    (tmp_path / ".supervisor.pid").write_text(json.dumps({"pid": os.getpid()}))
    mock_queue = MagicMock()
    app = create_app(queue=mock_queue)

    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.post("/api/tasks/task-kill-nr/kill")

    resp = asyncio.run(_run())
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "result": "closed"}
    assert not (task_dir / ".kill").exists(), (
        ".kill sentinel should NOT be written for non-running task"
    )
    mock_queue.close.assert_called_once_with("task-kill-nr", "killed")


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


def test_supervisor_dead_with_stale_tasks_reports_zero_active(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GET /api/supervisor reports active_count=0 for a dead supervisor (FR-42)."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    tasks_root = tmp_path / "tasks"
    _make_task_dir(tasks_root, "stale-1", "in_progress")
    _make_task_dir(tasks_root, "stale-2", "in_progress")
    # No .supervisor.pid file → supervisor is not running

    app = create_app()

    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get("/api/supervisor")

    resp = asyncio.run(_run())
    assert resp.status_code == 200
    data = resp.json()
    assert data["running"] is False
    assert data["active_count"] == 0
    assert data["free_slots"] == data["max_concurrent"]


def test_supervisor_running_counts_active_tasks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GET /api/supervisor counts only in_progress tasks with a live attempt (ADR 0009)."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    tasks_root = tmp_path / "tasks"
    live_dir = _make_task_dir(tasks_root, "active-1", "in_progress")
    _make_task_dir(tasks_root, "done-1", "completed")
    # A live latest attempt: start line plus run.json with no ended_at and a live pid.
    (live_dir / "attempts.jsonl").write_text(
        json.dumps(
            {
                "event": "start",
                "n": 1,
                "ts": "2026-01-01T00:00:00+00:00",
                "coder": "claude",
                "model": "sonnet",
                "worker": "task",
            }
        )
        + "\n"
    )
    attempt_dir = live_dir / "attempts" / "1"
    attempt_dir.mkdir(parents=True)
    (attempt_dir / "run.json").write_text(json.dumps({"pid": os.getpid()}))

    pid = os.getpid()
    (tmp_path / ".supervisor.pid").write_text(
        json.dumps(
            {
                "pid": pid,
                "started_at": "2024-01-01T00:00:00",
                "version_fingerprint": "x",
            }
        )
    )

    app = create_app()

    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get("/api/supervisor")

    resp = asyncio.run(_run())
    assert resp.status_code == 200
    data = resp.json()
    assert data["running"] is True
    assert data["active_count"] == 1
    assert data["free_slots"] == data["max_concurrent"] - 1
