"""Tests for config and chat routes (unit under test: serve/api/config.py, chat.py)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest

from fleet.core.config import RESTART_REQUIRED_FIELDS
from fleet.core.limits import TUNABLE_DOCS
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


def test_config_get_includes_restart_required(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GET /api/config lists the serve fields that need a restart (ADR 0009)."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    app = create_app()

    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get("/api/config")

    resp = asyncio.run(_run())
    assert resp.status_code == 200
    assert resp.json()["restart_required"] == list(RESTART_REQUIRED_FIELDS)
    assert set(RESTART_REQUIRED_FIELDS) == {
        "serve_host",
        "serve_port",
        "serve_cors_origins",
    }


def test_config_constants_lists_tunables_plus_retry_triage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GET /api/config/constants returns TUNABLE_DOCS + retry/triage rows."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    app = create_app()

    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get("/api/config/constants")

    resp = asyncio.run(_run())
    assert resp.status_code == 200
    rows = resp.json()["constants"]
    by_name = {row["name"]: row for row in rows}
    assert set(TUNABLE_DOCS) <= set(by_name)
    for name in (
        "FAILURE_WAIT_SEC",
        "FAILURE_JITTER_SEC",
        "WAITING_WAIT_SEC",
        "MAX_PER_TASK_QUESTIONS",
    ):
        assert name in by_name
    for row in rows:
        assert set(row) == {"name", "value", "unit", "doc", "module"}
        assert row["doc"]
    assert by_name["CONFIG_POLL_INTERVAL_SEC"]["module"] == "core/limits.py"
    assert by_name["FAILURE_WAIT_SEC"]["module"] == "core/retry_policy.py"
    assert by_name["MAX_PER_TASK_QUESTIONS"]["module"] == "core/triage_policy.py"
    assert by_name["CONFIG_POLL_INTERVAL_SEC"]["unit"] == "seconds"


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
