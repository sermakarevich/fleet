"""Tests for config and chat routes (unit under test: serve/api/config.py, chat.py)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest

from fleet.serve.app import create_app


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


def test_config_put_unknown_coder_is_422(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """PUT /api/config with an unknown coder is rejected (FR-43)."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    app = create_app()

    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.put("/api/config", json={"coder": "garbage_typo"})

    resp = asyncio.run(_run())
    assert resp.status_code == 422


def test_config_put_unknown_key_is_422(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """PUT /api/config with an unknown key returns 422 listing the key."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    app = create_app()

    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.put("/api/config", json={"no_such_key": "1"})

    resp = asyncio.run(_run())
    assert resp.status_code == 422
    assert "no_such_key" in resp.json()["error"]


def test_chat_answer_malformed_body_is_400(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """POST /api/chat/questions/{id}/answer with bad JSON returns 400."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    app = create_app()

    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.post(
                "/api/chat/questions/q1/answer",
                content=b"{not json",
                headers={"Content-Type": "application/json"},
            )

    resp = asyncio.run(_run())
    assert resp.status_code == 400
    assert "error" in resp.json()
