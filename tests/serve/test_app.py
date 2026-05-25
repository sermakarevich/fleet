"""Tests for src/fleet/serve/app.py — FR-48, FR-49."""
from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest

from fleet.serve.app import create_app


def test_healthz_returns_ok(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /healthz returns 200 with status=ok and fleet_home path (FR-48, FR-49)."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    app = create_app()

    async def _run() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get("/healthz")

    resp = asyncio.run(_run())
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["fleet_home"] == str(tmp_path)


def test_spa_serves_root_index(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """GET / serves index.html when ui_dist/ exists (FR-48)."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    ui_dist = tmp_path / "ui_dist"
    ui_dist.mkdir()
    (ui_dist / "index.html").write_text("<html>fleet-ui</html>")
    app = create_app()

    async def _run() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get("/")

    resp = asyncio.run(_run())
    assert resp.status_code == 200
    assert "fleet-ui" in resp.text


def test_spa_fallback_serves_index_for_unknown_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GET /tasks/abc serves index.html (SPA fallback) when ui_dist/ exists (FR-48)."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    ui_dist = tmp_path / "ui_dist"
    ui_dist.mkdir()
    (ui_dist / "index.html").write_text("<html>fleet-spa</html>")
    app = create_app()

    async def _run() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get("/tasks/abc")

    resp = asyncio.run(_run())
    assert resp.status_code == 200
    assert "fleet-spa" in resp.text


def test_no_ui_dist_app_starts_without_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """App starts and /healthz works even when ui_dist/ does not exist (FR-48)."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    # intentionally no ui_dist
    app = create_app()

    async def _run() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get("/healthz")

    resp = asyncio.run(_run())
    assert resp.status_code == 200
