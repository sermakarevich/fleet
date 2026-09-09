"""Tests for auth guards and param validation (unit under test: serve/auth.py, route bounds)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest
from starlette.testclient import TestClient

import fleet.serve.auth as auth_mod
from fleet.serve.app import create_app
from tests.serve.conftest import _make_task_dir


def test_healthz_requires_token_when_set(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """/healthz returns 401 without a token when FLEET_API_TOKEN is set."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    monkeypatch.setenv("FLEET_API_TOKEN", "secret")
    app = create_app()

    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get("/healthz")

    resp = asyncio.run(_run())
    assert resp.status_code == 401
    assert resp.json() == {"error": "unauthorized"}


def test_websocket_rejects_missing_token_when_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ws without a token closes with 4401 when FLEET_API_TOKEN is set."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    monkeypatch.setenv("FLEET_API_TOKEN", "secret")
    app = create_app()
    client = TestClient(app)
    try:
        with client.websocket_connect("/ws/events"):
            pass
        code = None
    except Exception as exc:  # noqa: BLE001 - close code surfaces via the error
        code = getattr(exc, "code", None)
    assert code == 4401


def test_events_limit_out_of_range_is_422(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /api/tasks/{id}/events?limit=999999 returns 422 (bounded query)."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    _make_task_dir(tmp_path / "tasks", "task-evlimit")

    app = create_app()

    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get("/api/tasks/task-evlimit/events?limit=999999")

    resp = asyncio.run(_run())
    assert resp.status_code == 422


def test_auth_uses_constant_time_compare() -> None:
    """serve/auth.py compares tokens with secrets.compare_digest, not ==."""
    src = Path(auth_mod.__file__).read_text(encoding="utf-8")
    assert "compare_digest" in src
