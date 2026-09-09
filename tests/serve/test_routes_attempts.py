"""Tests for attempt inspection routes (unit under test: serve/api attempt views)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest

from fleet.serve.app import create_app
from tests.serve.conftest import _make_attempt_dir


def test_attempt_summary_is_derived(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /api/tasks/{id}/attempts/{n}/summary renders on demand (no file)."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    _make_attempt_dir(tmp_path)
    app = create_app()

    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get("/api/tasks/task-attempt/attempts/1/summary")

    resp = asyncio.run(_run())
    assert resp.status_code == 200
    assert "Attempt 1 summary" in resp.json()["content"]
    assert "launch mode: continue" in resp.json()["content"]


def test_attempt_prompt_returns_recorded_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GET /api/tasks/{id}/attempts/{n}/prompt returns prompt.md."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    _make_attempt_dir(tmp_path)
    app = create_app()

    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get("/api/tasks/task-attempt/attempts/1/prompt")

    resp = asyncio.run(_run())
    assert resp.status_code == 200
    assert resp.json()["content"] == "the rendered prompt"


def test_attempt_prompt_404_when_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /api/tasks/{id}/attempts/{n}/prompt 404s without prompt.md."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    task_dir = _make_attempt_dir(tmp_path, "task-noprompt")
    (task_dir / "attempts" / "1" / "prompt.md").unlink()
    app = create_app()

    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get("/api/tasks/task-noprompt/attempts/1/prompt")

    resp = asyncio.run(_run())
    assert resp.status_code == 404


def test_attempt_state_returns_snapshot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /api/tasks/{id}/attempts/{n}/state returns the STATE.md snapshot."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    _make_attempt_dir(tmp_path)
    app = create_app()

    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get("/api/tasks/task-attempt/attempts/1/state")

    resp = asyncio.run(_run())
    assert resp.status_code == 200
    assert "do the thing" in resp.json()["content"]
