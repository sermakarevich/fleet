"""Tests for the artifact bundle and diff routes (unit under test: serve/api artifact views)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest

from fleet.serve.app import create_app
from tests.serve.conftest import _make_task_dir


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


def _get_bundle(app, task_id: str) -> httpx.Response:
    """GET the artifact bundle for *task_id* (sync wrapper for async client)."""

    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get(f"/api/tasks/{task_id}/artifacts")

    return asyncio.run(_run())


def test_artifact_bundle_full(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Bundle carries result, state, outputs, sorted docs and no worktree."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    task_dir = _make_task_dir(tmp_path / "tasks", "task-bundle")
    (task_dir / "RESULT.json").write_text('{"schema": 1, "status": "done"}')
    (task_dir / "STATE.md").write_text("## Next\nship it")
    outputs = task_dir / "outputs"
    outputs.mkdir()
    (outputs / "b.txt").write_text("b")
    (outputs / "a.txt").write_text("a")
    artifacts = task_dir / "artifacts"
    artifacts.mkdir()
    (artifacts / "RESEARCH.md").write_text("research notes")
    (artifacts / "candidates.json").write_text('{"candidates": []}')
    (artifacts / "RESULT.json").write_text("stale copy")

    resp = _get_bundle(create_app(), "task-bundle")
    assert resp.status_code == 200
    data = resp.json()
    assert '"status": "done"' in data["result"]["content"]
    assert data["result"]["truncated"] is False
    assert "ship it" in data["state"]["content"]
    assert [f["name"] for f in data["outputs"]] == ["a.txt", "b.txt"]
    assert all(Path(f["path"]).is_absolute() for f in data["outputs"])
    assert [d["name"] for d in data["docs"]] == ["RESEARCH.md", "candidates.json"]
    assert data["worktree"] is None


def test_artifact_bundle_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Bundle for a bare task dir is all Nones and empties, never an error."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    _make_task_dir(tmp_path / "tasks", "task-empty-bundle")

    resp = _get_bundle(create_app(), "task-empty-bundle")
    assert resp.status_code == 200
    assert resp.json() == {
        "result": None,
        "state": None,
        "outputs": [],
        "docs": [],
        "files": [],
        "worktree": None,
    }


def test_artifact_bundle_missing_worktree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Bundle echoes worktree keys with exists False when the dir is gone."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    missing = tmp_path / "gone"
    _make_task_dir(
        tmp_path / "tasks",
        "task-wt-bundle",
        repo_root=str(tmp_path),
        base_ref="main",
        worktree_path=str(missing),
    )

    resp = _get_bundle(create_app(), "task-wt-bundle")
    assert resp.status_code == 200
    assert resp.json()["worktree"] == {
        "repo_root": str(tmp_path),
        "base_ref": "main",
        "worktree_path": str(missing),
        "exists": False,
    }


def test_artifact_bundle_missing_task(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Bundle for an unknown task id is a 404."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    assert _get_bundle(create_app(), "no-such-task").status_code == 404
