"""Tests for the beads portal REST routes (BD tab)."""
from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path

import httpx
import pytest

from fleet.serve.app import create_app


def _fake_bd(returncode: int = 0, stdout: str = "", stderr: str = ""):
    """Build a fake subprocess.run that records its invocations."""

    def _run(args, capture_output=True, text=True, cwd=None):  # noqa: ANN001
        _run.calls.append(list(args))
        return subprocess.CompletedProcess(args, returncode, stdout, stderr)

    _run.calls = []
    return _run


def _get(app, path: str, **kwargs) -> httpx.Response:
    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get(path, **kwargs)

    return asyncio.run(_run())


def _post(app, path: str, **kwargs) -> httpx.Response:
    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.post(path, **kwargs)

    return asyncio.run(_run())


def test_beads_list_returns_parsed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /api/beads parses `bd list` output into summaries."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    payload = json.dumps(
        [
            {
                "id": "fleet-1",
                "title": "One",
                "status": "open",
                "assignee": "claude",
                "priority": 1,
                "dependency_count": 2,
            }
        ]
    )
    fake = _fake_bd(0, payload)
    monkeypatch.setattr("fleet.serve.routes.beads.subprocess.run", fake)
    app = create_app()

    resp = _get(app, "/api/beads")
    assert resp.status_code == 200
    beads = resp.json()["beads"]
    assert len(beads) == 1
    assert beads[0]["id"] == "fleet-1"
    assert beads[0]["assignee"] == "claude"
    assert beads[0]["dependency_count"] == 2
    assert fake.calls[0][:2] == ["bd", "list"]


def test_beads_list_handles_envelope(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /api/beads unwraps the {data: [...]} envelope form."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    payload = json.dumps({"data": [{"id": "fleet-2", "title": "Two", "status": "closed"}]})
    monkeypatch.setattr("fleet.serve.routes.beads.subprocess.run", _fake_bd(0, payload))
    app = create_app()

    resp = _get(app, "/api/beads")
    assert resp.status_code == 200
    assert resp.json()["beads"][0]["id"] == "fleet-2"


def test_beads_list_502_on_bd_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /api/beads returns 502 when bd exits non-zero (surfaces to drawer)."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    monkeypatch.setattr("fleet.serve.routes.beads.subprocess.run", _fake_bd(1, "", "boom"))
    app = create_app()

    resp = _get(app, "/api/beads")
    assert resp.status_code == 502
    assert "boom" in resp.json()["error"]


def test_bead_detail_returns_deps_and_comments(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /api/beads/{id} returns description, notes, dependencies and comments."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    payload = json.dumps(
        [
            {
                "id": "fleet-3",
                "title": "Three",
                "status": "blocked",
                "description": "the full description",
                "notes": "retry limit exhausted",
                "dependencies": [
                    {"id": "fleet-9", "title": "dep", "status": "open", "dependency_type": "blocks"}
                ],
                "comments": [{"id": 1, "author": "bot", "text": "hi", "created_at": "now"}],
            }
        ]
    )
    monkeypatch.setattr("fleet.serve.routes.beads.subprocess.run", _fake_bd(0, payload))
    app = create_app()

    resp = _get(app, "/api/beads/fleet-3")
    assert resp.status_code == 200
    data = resp.json()
    assert data["description"] == "the full description"
    assert data["notes"] == "retry limit exhausted"
    assert data["dependencies"][0]["id"] == "fleet-9"
    assert data["dependencies"][0]["status"] == "open"
    assert data["comments"][0]["text"] == "hi"


def test_bead_set_status_valid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """POST /api/beads/{id}/status with a valid status runs `bd update --status`."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    fake = _fake_bd(0, "")
    monkeypatch.setattr("fleet.serve.routes.beads.subprocess.run", fake)
    app = create_app()

    resp = _post(app, "/api/beads/fleet-4/status", json={"status": "blocked"})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert fake.calls[0] == ["bd", "update", "fleet-4", "--status", "blocked"]


def test_bead_set_status_invalid_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """POST /api/beads/{id}/status rejects an unknown status without calling bd."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    fake = _fake_bd(0, "")
    monkeypatch.setattr("fleet.serve.routes.beads.subprocess.run", fake)
    app = create_app()

    resp = _post(app, "/api/beads/fleet-4/status", json={"status": "bogus"})
    assert resp.status_code == 422
    assert fake.calls == []


def test_bead_unblock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """POST /api/beads/{id}/unblock runs `bd update --status open`."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    fake = _fake_bd(0, "")
    monkeypatch.setattr("fleet.serve.routes.beads.subprocess.run", fake)
    app = create_app()

    resp = _post(app, "/api/beads/fleet-5/unblock")
    assert resp.status_code == 200
    assert fake.calls[0] == ["bd", "update", "fleet-5", "--status", "open"]


def test_bead_remove_assignee(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """POST /api/beads/{id}/remove-assignee runs `bd update --assignee ''`."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    fake = _fake_bd(0, "")
    monkeypatch.setattr("fleet.serve.routes.beads.subprocess.run", fake)
    app = create_app()

    resp = _post(app, "/api/beads/fleet-6/remove-assignee")
    assert resp.status_code == 200
    assert fake.calls[0] == ["bd", "update", "fleet-6", "--assignee", ""]


def test_bead_update_502_on_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A failing `bd update` surfaces as 502."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    monkeypatch.setattr("fleet.serve.routes.beads.subprocess.run", _fake_bd(1, "", "nope"))
    app = create_app()

    resp = _post(app, "/api/beads/fleet-7/unblock")
    assert resp.status_code == 502
    assert "nope" in resp.json()["error"]
