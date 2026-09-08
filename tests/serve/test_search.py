"""Tests for full-text search endpoint (FR-47)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from fleet.serve.api.search import search_tasks
from fleet.serve.app import create_app


def _make_task(
    tasks_root: Path,
    task_id: str,
    title: str = "Task",
    description: str = "",
    *,
    state: str = "",
) -> Path:
    task_dir = tasks_root / task_id
    task_dir.mkdir(parents=True)
    data = {"id": task_id, "title": title, "description": description, "status": "in_progress"}
    (task_dir / "task.json").write_text(json.dumps(data))
    if state:
        (task_dir / "STATE.md").write_text(state)
    return task_dir


def test_search_tasks_title_match(tmp_path: Path) -> None:
    """Searching by title fragment returns correct result."""
    tasks_root = tmp_path / "tasks"
    _make_task(tasks_root, "t1", title="refactor auth module")
    _make_task(tasks_root, "t2", title="implement dashboard")

    results = search_tasks(tmp_path, "auth")
    assert len(results) == 1
    assert results[0].task_id == "t1"
    assert results[0].source == "title"


def test_search_tasks_description_match(tmp_path: Path) -> None:
    """Searching by description returns correct result."""
    tasks_root = tmp_path / "tasks"
    _make_task(tasks_root, "t1", title="task one", description="auth system refactor")

    results = search_tasks(tmp_path, "auth")
    assert any(r.source == "description" for r in results)


def test_search_tasks_state_match(tmp_path: Path) -> None:
    """Searching STATE.md content returns result with source=state."""
    tasks_root = tmp_path / "tasks"
    _make_task(tasks_root, "t1", title="task one", state="## Facts\nrefactor auth is needed")

    results = search_tasks(tmp_path, "auth")
    assert any(r.source == "state" for r in results)
    assert results[0].task_id == "t1"


def test_search_tasks_legacy_dir_match(tmp_path: Path) -> None:
    """Old task dirs (no STATE.md) are still searchable via the legacy view."""
    tasks_root = tmp_path / "tasks"
    task_dir = _make_task(tasks_root, "t1", title="task one")
    artifacts = task_dir / "artifacts"
    artifacts.mkdir()
    (artifacts / "KNOWLEDGE.md").write_text("refactor auth is needed")

    results = search_tasks(tmp_path, "auth")
    assert any(r.source == "state" for r in results)


def test_search_tasks_limit_20(tmp_path: Path) -> None:
    """Results are capped at 20 even when more matches exist."""
    tasks_root = tmp_path / "tasks"
    for i in range(25):
        _make_task(tasks_root, f"t{i:02d}", title=f"auth task {i}")

    results = search_tasks(tmp_path, "auth")
    assert len(results) == 20


def test_search_tasks_case_insensitive(tmp_path: Path) -> None:
    """Search is case-insensitive."""
    tasks_root = tmp_path / "tasks"
    _make_task(tasks_root, "t1", title="Refactor AUTH Module")

    results = search_tasks(tmp_path, "auth")
    assert len(results) == 1


def test_search_tasks_empty_query(tmp_path: Path) -> None:
    """Empty query returns no results."""
    results = search_tasks(tmp_path, "")
    assert results == []


def test_search_tasks_context_snippet(tmp_path: Path) -> None:
    """match_context is a non-empty snippet around the match."""
    tasks_root = tmp_path / "tasks"
    _make_task(tasks_root, "t1", title="auth module setup")

    results = search_tasks(tmp_path, "auth")
    assert len(results) == 1
    assert "auth" in results[0].match_context.lower()


def test_search_endpoint_returns_results(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /api/search?q=... returns matching results."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    tasks_root = tmp_path / "tasks"
    _make_task(tasks_root, "t1", title="refactor auth module")

    app = create_app()

    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get("/api/search?q=auth")

    resp = asyncio.run(_run())
    assert resp.status_code == 200
    data = resp.json()
    assert "results" in data
    assert len(data["results"]) == 1
    r = data["results"][0]
    assert r["task_id"] == "t1"
    assert r["source"] == "title"
    assert "task_title" in r
    assert "match_context" in r


def test_search_endpoint_empty_q_returns_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GET /api/search?q= returns empty results for empty query."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    app = create_app()

    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get("/api/search?q=")

    resp = asyncio.run(_run())
    assert resp.status_code == 200
    assert resp.json() == {"results": []}


def test_search_endpoint_no_q_returns_422(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /api/search (no q param) returns 422."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    app = create_app()

    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get("/api/search")

    resp = asyncio.run(_run())
    assert resp.status_code == 422
