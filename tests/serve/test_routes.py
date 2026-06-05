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
    """POST /api/tasks/{id}/kill writes .kill sentinel and returns 200 (FR-07)."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    tasks_root = tmp_path / "tasks"
    task_dir = _make_task_dir(tasks_root, "task-kill", "in_progress")
    app = create_app()

    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.post("/api/tasks/task-kill/kill")

    resp = asyncio.run(_run())
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert (task_dir / ".kill").exists(), ".kill sentinel should be written"


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


def test_task_summary_includes_priority_and_depends_on(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /api/tasks includes priority and depends_on in each summary (FR-10, FR-11)."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    tasks_root = tmp_path / "tasks"
    _make_task_dir(
        tasks_root,
        "task-bd1",
        "open",
        priority=5,
        depends_on=["task-x", "task-y"],
    )
    _make_task_dir(tasks_root, "task-bd2", "in_progress")

    app = create_app()

    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get("/api/tasks")

    resp = asyncio.run(_run())
    assert resp.status_code == 200
    tasks = {t["id"]: t for t in resp.json()["tasks"]}

    assert tasks["task-bd1"]["priority"] == 5
    assert tasks["task-bd1"]["depends_on"] == ["task-x", "task-y"]
    assert tasks["task-bd2"]["priority"] is None
    assert tasks["task-bd2"]["depends_on"] == []


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


# ---------------------------------------------------------------------------
# Artifact endpoints (FR-11..FR-21)
# ---------------------------------------------------------------------------

def test_artifact_plan_returns_content(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /api/tasks/{id}/artifacts/plan returns content and mtime (FR-14)."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    task_dir = _make_task_dir(tmp_path / "tasks", "task-plan")
    artifacts = task_dir / "artifacts"
    artifacts.mkdir()
    (artifacts / "PLAN_AND_STATUS.md").write_text("# Plan\ncontent here")

    app = create_app()

    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get("/api/tasks/task-plan/artifacts/plan")

    resp = asyncio.run(_run())
    assert resp.status_code == 200
    data = resp.json()
    assert data["content"] == "# Plan\ncontent here"
    assert isinstance(data["mtime"], float)


def test_artifact_plan_404(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /api/tasks/{id}/artifacts/plan returns 404 when file missing (FR-14)."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    _make_task_dir(tmp_path / "tasks", "task-noplan")

    app = create_app()

    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get("/api/tasks/task-noplan/artifacts/plan")

    resp = asyncio.run(_run())
    assert resp.status_code == 404


def test_artifact_knowledge_returns_content(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /api/tasks/{id}/artifacts/knowledge returns KNOWLEDGE.md content (FR-15)."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    task_dir = _make_task_dir(tmp_path / "tasks", "task-kb")
    artifacts = task_dir / "artifacts"
    artifacts.mkdir()
    (artifacts / "KNOWLEDGE.md").write_text("## Surface area\nsome knowledge")

    app = create_app()

    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get("/api/tasks/task-kb/artifacts/knowledge")

    resp = asyncio.run(_run())
    assert resp.status_code == 200
    data = resp.json()
    assert "some knowledge" in data["content"]
    assert isinstance(data["mtime"], float)


def test_artifact_qa_returns_content(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /api/tasks/{id}/artifacts/qa returns Q&A.md content (FR-16)."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    task_dir = _make_task_dir(tmp_path / "tasks", "task-qa")
    artifacts = task_dir / "artifacts"
    artifacts.mkdir()
    (artifacts / "Q&A.md").write_text("## Q: What?\n## A: This.")

    app = create_app()

    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get("/api/tasks/task-qa/artifacts/qa")

    resp = asyncio.run(_run())
    assert resp.status_code == 200
    data = resp.json()
    assert "## Q: What?" in data["content"]
    assert isinstance(data["mtime"], float)


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


def test_files_returns_counts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /api/tasks/{id}/files returns per-file read/edit/write counts (FR-20)."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    task_dir = _make_task_dir(tmp_path / "tasks", "task-files")
    events = [
        {"kind": "tool_use", "tool_name": "Read", "raw": {"input": {"file_path": "/foo.py"}}},
        {"kind": "tool_use", "tool_name": "Edit", "raw": {"input": {"file_path": "/foo.py"}}},
        {"kind": "tool_use", "tool_name": "Write", "raw": {"input": {"file_path": "/bar.py"}}},
        {"kind": "tool_use", "tool_name": "Read", "raw": {"input": {"file_path": "/foo.py"}}},
        {"kind": "tool_result", "tool_name": None, "raw": {}},  # non-tool_use, ignored
    ]
    (task_dir / "events.jsonl").write_text("\n".join(json.dumps(e) for e in events))

    app = create_app()

    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get("/api/tasks/task-files/files")

    resp = asyncio.run(_run())
    assert resp.status_code == 200
    data = resp.json()
    assert "files" in data
    files_map = {f["path"]: f for f in data["files"]}
    assert "/foo.py" in files_map
    assert files_map["/foo.py"]["read"] == 2
    assert files_map["/foo.py"]["edit"] == 1
    assert "/bar.py" in files_map
    assert files_map["/bar.py"]["write"] == 1
