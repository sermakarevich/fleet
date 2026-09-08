"""Tests for optional bearer-token auth via FLEET_API_TOKEN (fleet-8q1n9)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest

from fleet.serve.app import create_app


def _get(path: str, app, headers: dict | None = None) -> httpx.Response:
    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get(path, headers=headers or {})

    return asyncio.run(_run())


def test_no_token_env_means_open(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Token env unset -> GET /api/tasks returns 200."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    monkeypatch.delenv("FLEET_API_TOKEN", raising=False)
    app = create_app()
    resp = _get("/api/tasks", app)
    assert resp.status_code == 200


def test_token_set_requires_auth_but_healthz_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FLEET_API_TOKEN=secret and no header -> 401; /healthz still 200."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    monkeypatch.setenv("FLEET_API_TOKEN", "secret")
    app = create_app()
    resp = _get("/api/tasks", app)
    assert resp.status_code == 401
    assert resp.json() == {"detail": "unauthorized"}
    health = _get("/healthz", app)
    assert health.status_code == 200


def test_token_accepted_via_header_or_query(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FLEET_API_TOKEN=secret with Bearer header -> 200; with ?token= -> 200."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    monkeypatch.setenv("FLEET_API_TOKEN", "secret")
    app = create_app()
    via_header = _get("/api/tasks", app, headers={"Authorization": "Bearer secret"})
    assert via_header.status_code == 200
    via_query = _get("/api/tasks?token=secret", app)
    assert via_query.status_code == 200
