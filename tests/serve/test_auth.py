"""Tests for bearer-token auth via FLEET_API_TOKEN (ADR 0006 bead 23).

Auth is a router-level ``require_token`` dependency (constant-time compare):
HTTP routes accept ``Authorization: Bearer`` or ``X-Fleet-Token`` headers only
(``?token=`` is rejected on HTTP so tokens never land in access logs); the two
websocket endpoints additionally accept ``?token=`` because browsers cannot
set headers on websockets. ``/healthz`` is covered like every other route.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest
from starlette.testclient import TestClient

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


def test_token_set_guards_api_and_healthz(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """FLEET_API_TOKEN=secret and no header -> 401 on /api/* and /healthz."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    monkeypatch.setenv("FLEET_API_TOKEN", "secret")
    app = create_app()
    resp = _get("/api/tasks", app)
    assert resp.status_code == 401
    assert resp.json() == {"error": "unauthorized"}
    health = _get("/healthz", app)
    assert health.status_code == 401
    assert health.json() == {"error": "unauthorized"}


def test_token_accepted_via_either_header(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Bearer and X-Fleet-Token headers both authenticate (healthz included)."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    monkeypatch.setenv("FLEET_API_TOKEN", "secret")
    app = create_app()
    via_bearer = _get("/api/tasks", app, headers={"Authorization": "Bearer secret"})
    assert via_bearer.status_code == 200
    via_fleet_token = _get("/api/tasks", app, headers={"X-Fleet-Token": "secret"})
    assert via_fleet_token.status_code == 200
    health = _get("/healthz", app, headers={"Authorization": "Bearer secret"})
    assert health.status_code == 200


def test_token_query_param_rejected_on_http(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """?token= on HTTP routes stays 401 (?token= is websocket-only)."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    monkeypatch.setenv("FLEET_API_TOKEN", "secret")
    app = create_app()
    via_query = _get("/api/tasks?token=secret", app)
    assert via_query.status_code == 401


def test_websocket_query_token_accepted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """?token= authenticates websocket endpoints (browsers set no headers)."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    monkeypatch.setenv("FLEET_API_TOKEN", "secret")
    app = create_app()
    client = TestClient(app)
    with client.websocket_connect("/ws/events?token=secret") as ws:
        ws.send_text("hello")


def test_websocket_without_token_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Websocket without a token closes with 4401 when a token is set."""
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
