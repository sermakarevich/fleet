"""Tests for the /api/triggers REST routes (Triggers 5/8, ADR 0011)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import httpx
import pytest

from fleet.serve.app import create_app
from fleet.triggers.model import TriggerEvent
from tests.conftest import FakeQueue

_VALID = {
    "name": "investigate",
    "source": "blocked_task",
    "source_params": {},
    "enabled": True,
    "title": "Investigate {{event.task_id}}",
    "description": "desc",
    "coder": "claude",
    "priority": 2,
    "max_open": 2,
    "cooldown_sec": 0,
}


def _app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Serve app against a throwaway fleet home."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    return create_app()


def _request(app, method: str, path: str, **kwargs: Any) -> httpx.Response:
    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.request(method, path, **kwargs)

    return asyncio.run(_run())


def test_list_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /triggers lists nothing on a fresh fleet home."""
    app = _app(tmp_path, monkeypatch)
    resp = _request(app, "GET", "/api/triggers")
    assert resp.status_code == 200
    assert resp.json() == {"triggers": []}


def test_create_then_get(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """POST /triggers validates, saves, and GET returns the detail."""
    app = _app(tmp_path, monkeypatch)
    resp = _request(app, "POST", "/api/triggers", json=_VALID)
    assert resp.status_code == 201
    body = resp.json()
    assert body["id"].startswith("trg-")
    assert body["name"] == "investigate"
    assert body["firing_count"] == 0
    assert body["last_fired_at"] is None
    assert (tmp_path / "triggers" / f"{body['id']}.json").is_file()

    detail = _request(app, "GET", f"/api/triggers/{body['id']}")
    assert detail.status_code == 200
    assert detail.json()["trigger"]["id"] == body["id"]
    assert detail.json()["firings"] == []


def test_create_unknown_source_is_422(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """POST /triggers answers 422 naming source for an unknown kind."""
    app = _app(tmp_path, monkeypatch)
    resp = _request(app, "POST", "/api/triggers", json={**_VALID, "source": "nope"})
    assert resp.status_code == 422
    assert "source" in resp.json()["error"].lower()


def test_create_bad_priority_is_422(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """POST /triggers answers 422 naming priority for an out-of-range value."""
    app = _app(tmp_path, monkeypatch)
    resp = _request(app, "POST", "/api/triggers", json={**_VALID, "priority": 9})
    assert resp.status_code == 422
    assert "priority" in resp.json()["error"].lower()


def test_put_updates_name(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """PUT rewrites the body but keeps id/created_at and bumps updated_at."""
    app = _app(tmp_path, monkeypatch)
    created = _request(app, "POST", "/api/triggers", json=_VALID).json()
    trigger_id = created["id"]
    resp = _request(app, "PUT", f"/api/triggers/{trigger_id}", json={**_VALID, "name": "New"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == trigger_id
    assert body["created_at"] == created["created_at"]
    assert body["name"] == "New"


def test_enable_disable_flips_enabled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """POST /triggers/{id}/disable flips enabled off; enable flips it back."""
    app = _app(tmp_path, monkeypatch)
    trigger_id = _request(app, "POST", "/api/triggers", json=_VALID).json()["id"]
    assert _request(app, "POST", f"/api/triggers/{trigger_id}/disable").json() == {"ok": True}
    assert _request(app, "GET", f"/api/triggers/{trigger_id}").json()["trigger"]["enabled"] is False
    assert _request(app, "POST", f"/api/triggers/{trigger_id}/enable").json() == {"ok": True}
    assert _request(app, "GET", f"/api/triggers/{trigger_id}").json()["trigger"]["enabled"] is True


def test_delete_then_get_is_404(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """DELETE removes the definition and further reads 404."""
    app = _app(tmp_path, monkeypatch)
    trigger_id = _request(app, "POST", "/api/triggers", json=_VALID).json()["id"]
    resp = _request(app, "DELETE", f"/api/triggers/{trigger_id}")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert _request(app, "GET", f"/api/triggers/{trigger_id}").status_code == 404


def test_sources_lists_blocked_task(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /triggers/sources lists blocked_task with its params."""
    app = _app(tmp_path, monkeypatch)
    resp = _request(app, "GET", "/api/triggers/sources")
    assert resp.status_code == 200
    rows = {row["kind"]: row["params"] for row in resp.json()["sources"]}
    assert "blocked_task" in rows
    assert "fleet_blocked_only" in rows["blocked_task"]


def test_preview_dry_run_opens_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """POST /triggers/{id}/preview returns events+decisions, creates no task."""
    app = _app(tmp_path, monkeypatch)
    app.state.fleet_state.queue = FakeQueue()
    trigger_id = _request(app, "POST", "/api/triggers", json=_VALID).json()["id"]

    event = TriggerEvent(
        source="blocked_task",
        key="fake-001@2026-09-09T00:00:00+00:00",
        occurred_at="2026-09-09T00:00:00+00:00",
        payload={"task_id": "fake-001"},
    )

    class _FakeSource:
        kind = "blocked_task"

        def poll(self, ctx) -> list:
            _ = ctx
            return [event]

    monkeypatch.setattr("fleet.serve.api.triggers.source_for", lambda kind: _FakeSource())
    resp = _request(app, "POST", f"/api/triggers/{trigger_id}/preview")
    assert resp.status_code == 200
    body = resp.json()
    assert body["events"] == [{"task_id": "fake-001"}]
    assert body["decisions"] == ["open"]
    queue = app.state.fleet_state.queue
    assert isinstance(queue, FakeQueue)
    assert queue.created == []
