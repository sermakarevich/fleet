"""Tests for GET /api/tasks/{id}/diff (ADR 0017 U1 worktree-aware diff)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest

from fleet.serve.api import tasks_diff
from fleet.serve.app import create_app
from tests.serve.conftest import _make_task_dir


def _get(app, path: str) -> httpx.Response:
    """GET *path* against the serve app (sync wrapper for the async client)."""

    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get(path)

    return asyncio.run(_run())


def _patch_git_diff(monkeypatch: pytest.MonkeyPatch, diff: str = "DIFF", note: str = "") -> list:
    """Replace tasks_diff._git_diff with a recorder returning (diff, note)."""
    calls: list = []

    async def _fake(cwd: str, base_ref: str | None) -> tuple[str, str]:
        calls.append((cwd, base_ref))
        return diff, note

    monkeypatch.setattr(tasks_diff, "_git_diff", _fake)
    return calls


def test_diff_uses_worktree_and_base_ref(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A task with worktree_path diffs the worktree against base_ref."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    worktree = tmp_path / "wt"
    worktree.mkdir()
    _make_task_dir(
        tmp_path / "tasks",
        "task-wt",
        worktree_path=str(worktree),
        base_ref="main",
        repo_root=str(tmp_path),
    )
    calls = _patch_git_diff(monkeypatch)
    resp = _get(create_app(), "/api/tasks/task-wt/diff")
    assert resp.status_code == 200
    assert resp.json() == {"diff": "DIFF", "note": ""}
    assert calls == [(str(worktree), "main")]


def test_diff_falls_back_to_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A task with only cwd diffs the cwd with no base ref."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    _make_task_dir(tmp_path / "tasks", "task-cwd", cwd="/repo")
    calls = _patch_git_diff(monkeypatch)
    resp = _get(create_app(), "/api/tasks/task-cwd/diff")
    assert resp.status_code == 200
    assert resp.json() == {"diff": "DIFF", "note": ""}
    assert calls == [("/repo", None)]


def test_diff_without_cwd_reports_note(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No cwd and no worktree is an empty diff with a 'no working directory' note."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    _make_task_dir(tmp_path / "tasks", "task-nocwd", cwd=None)
    calls = _patch_git_diff(monkeypatch)
    resp = _get(create_app(), "/api/tasks/task-nocwd/diff")
    assert resp.status_code == 200
    assert resp.json() == {"diff": "", "note": "no working directory"}
    assert calls == []


def test_diff_missing_worktree_reports_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A worktree_path that no longer exists reports 'worktree removed'."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    missing = tmp_path / "gone"
    _make_task_dir(
        tmp_path / "tasks",
        "task-gone",
        worktree_path=str(missing),
        base_ref="main",
    )
    calls = _patch_git_diff(monkeypatch)
    resp = _get(create_app(), "/api/tasks/task-gone/diff")
    assert resp.status_code == 200
    assert resp.json() == {"diff": "", "note": "worktree removed"}
    assert calls == []
