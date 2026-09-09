"""Tests for artifact/log/stderr/diff routes (unit under test: serve/api artifact views)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from fleet.serve.app import create_app
from tests.serve.conftest import _make_attempt_dir, _make_task_dir


def test_artifact_state_returns_content(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /api/tasks/{id}/artifacts/state returns STATE.md content and mtime."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    task_dir = _make_task_dir(tmp_path / "tasks", "task-state")
    (task_dir / "STATE.md").write_text("## Next\ndo the thing")

    app = create_app()

    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get("/api/tasks/task-state/artifacts/state")

    resp = asyncio.run(_run())
    assert resp.status_code == 200
    data = resp.json()
    assert "do the thing" in data["content"]
    assert isinstance(data["mtime"], float)


def test_artifact_state_falls_back_to_legacy_view(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Old tasks with no STATE.md render the legacy artifacts view."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    task_dir = _make_task_dir(tmp_path / "tasks", "task-old-state")
    artifacts = task_dir / "artifacts"
    artifacts.mkdir()
    (artifacts / "KNOWLEDGE.md").write_text("old fact")

    app = create_app()

    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get("/api/tasks/task-old-state/artifacts/state")

    resp = asyncio.run(_run())
    assert resp.status_code == 200
    assert "old fact" in resp.json()["content"]


def test_artifact_state_404(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /api/tasks/{id}/artifacts/state returns 404 when nothing to show."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    _make_task_dir(tmp_path / "tasks", "task-nostate")

    app = create_app()

    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get("/api/tasks/task-nostate/artifacts/state")

    resp = asyncio.run(_run())
    assert resp.status_code == 404


def test_artifact_result_returns_content(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /api/tasks/{id}/artifacts/result returns RESULT.json content."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    task_dir = _make_task_dir(tmp_path / "tasks", "task-result")
    (task_dir / "RESULT.json").write_text('{"schema": 1, "status": "done", "summary": "ok"}')

    app = create_app()

    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get("/api/tasks/task-result/artifacts/result")

    resp = asyncio.run(_run())
    assert resp.status_code == 200
    data = resp.json()
    assert '"status": "done"' in data["content"]


def test_artifact_result_404(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /api/tasks/{id}/artifacts/result returns 404 when file missing."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    _make_task_dir(tmp_path / "tasks", "task-noresult")

    app = create_app()

    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get("/api/tasks/task-noresult/artifacts/result")

    resp = asyncio.run(_run())
    assert resp.status_code == 404


def test_artifact_outputs_lists_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /api/tasks/{id}/artifacts/outputs lists outputs/ files."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    task_dir = _make_task_dir(tmp_path / "tasks", "task-outputs")
    outputs = task_dir / "outputs"
    outputs.mkdir()
    (outputs / "report.md").write_text("report")
    app = create_app()

    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get("/api/tasks/task-outputs/artifacts/outputs")

    resp = asyncio.run(_run())
    assert resp.status_code == 200
    assert resp.json() == {"files": ["report.md"]}


def test_artifact_result_falls_back_to_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Post-reap the live RESULT.json is gone; the snapshot still serves."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    _make_attempt_dir(tmp_path)
    app = create_app()

    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get("/api/tasks/task-attempt/artifacts/result")

    resp = asyncio.run(_run())
    assert resp.status_code == 200
    assert '"status": "partial"' in resp.json()["content"]


def test_logs_returns_parsed_lines(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /api/tasks/{id}/logs returns parsed log lines (FR-17)."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    task_dir = _make_task_dir(tmp_path / "tasks", "task-logs")
    log_lines = [
        json.dumps({"timestamp": "2024-01-01T00:00:00", "level": "info", "event": "started"}),
        json.dumps({"timestamp": "2024-01-01T00:00:01", "level": "error", "event": "failed"}),
        "bad line",  # malformed line should be skipped
    ]
    (task_dir / "log.jsonl").write_text("\n".join(log_lines))

    app = create_app()

    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get("/api/tasks/task-logs/logs")

    resp = asyncio.run(_run())
    assert resp.status_code == 200
    data = resp.json()
    assert "lines" in data
    assert len(data["lines"]) == 2
    assert data["lines"][0]["level"] == "info"
    assert data["lines"][0]["message"] == "started"
    assert data["lines"][1]["level"] == "error"


def test_logs_level_filter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /api/tasks/{id}/logs?level=error returns only error lines (FR-17)."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    task_dir = _make_task_dir(tmp_path / "tasks", "task-logfilter")
    log_lines = [
        json.dumps({"timestamp": "2024-01-01T00:00:00", "level": "info", "event": "ok"}),
        json.dumps({"timestamp": "2024-01-01T00:00:01", "level": "error", "event": "boom"}),
    ]
    (task_dir / "log.jsonl").write_text("\n".join(log_lines))

    app = create_app()

    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get("/api/tasks/task-logfilter/logs?level=error")

    resp = asyncio.run(_run())
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["lines"]) == 1
    assert data["lines"][0]["level"] == "error"


def test_stderr_returns_content(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /api/tasks/{id}/stderr returns raw stderr content (FR-18)."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    task_dir = _make_task_dir(tmp_path / "tasks", "task-stderr")
    (task_dir / "log.stderr").write_text("some error output\nanother line")

    app = create_app()

    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get("/api/tasks/task-stderr/stderr")

    resp = asyncio.run(_run())
    assert resp.status_code == 200
    data = resp.json()
    assert "some error output" in data["content"]


def test_stderr_empty_when_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /api/tasks/{id}/stderr returns empty content when log.stderr absent (FR-18)."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    _make_task_dir(tmp_path / "tasks", "task-nostderr")

    app = create_app()

    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get("/api/tasks/task-nostderr/stderr")

    resp = asyncio.run(_run())
    assert resp.status_code == 200
    assert resp.json()["content"] == ""


def test_diff_returns_empty_for_non_git(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /api/tasks/{id}/diff returns empty diff when cwd is not a git repo (FR-19)."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    work_dir = tmp_path / "workdir"
    work_dir.mkdir()
    _make_task_dir(tmp_path / "tasks", "task-diff", cwd=str(work_dir))

    app = create_app()

    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get("/api/tasks/task-diff/diff")

    resp = asyncio.run(_run())
    assert resp.status_code == 200
    assert resp.json()["diff"] == ""
