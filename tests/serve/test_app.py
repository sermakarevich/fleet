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
