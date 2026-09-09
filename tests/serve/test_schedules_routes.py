"""Tests for the /api/schedules REST routes (Sched 4/6, ADR 0007)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import httpx
import pytest

from fleet.serve.app import create_app
from fleet.workflows.model import Defaults, Stage, Step, Workflow
from fleet.workflows.store import WorkflowStore
from tests.conftest import FakeQueue

_VALID = {
    "name": "triage",
    "cron": "* * * * *",
    "timezone": "UTC",
    "enabled": True,
    "title": "Triage {n}",
    "description": "desc",
    "coder": "claude",
    "priority": 2,
    "overlap": "skip",
}


class _StubBeads:
    """Stand-in for beads_client: records run_json calls, returns canned rows."""

    def __init__(self, items: list[dict[str, Any]]) -> None:
        self._items = items
        self.calls: list[list[str]] = []

    def run_json(self, args: list[str], **kwargs: Any) -> list[dict[str, Any]]:
        """Record argv and return the canned bead rows."""
        _ = kwargs
        self.calls.append(list(args))
        return self._items


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


def _schedules_dir(tmp_path: Path) -> Path:
    return tmp_path / "schedules"


def test_create_returns_201_and_writes_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """POST /schedules validates, saves, and answers 201 with the view."""
    app = _app(tmp_path, monkeypatch)
    resp = _request(app, "POST", "/api/schedules", json={**_VALID, "cwd": str(tmp_path)})
    assert resp.status_code == 201
    body = resp.json()
    assert body["id"].startswith("sch-")
    assert body["name"] == "triage"
    assert body["next_fire_at"] is not None
    assert body["run_count"] == 0
    assert body["last_run"] is None
    assert (_schedules_dir(tmp_path) / f"{body['id']}.json").is_file()


def test_create_bad_cron_names_field(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """POST /schedules with a bad cron answers 422 naming the cron field."""
    app = _app(tmp_path, monkeypatch)
    resp = _request(app, "POST", "/api/schedules", json={**_VALID, "cron": "nope"})
    assert resp.status_code == 422
    assert "cron" in resp.json()["error"].lower()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("timezone", "Mars/Olympus"),
        ("coder", "nope-coder"),
        ("cwd", "/does/not/exist"),
        ("priority", 9),
        ("overlap", "explode"),
        ("name", ""),
        ("title", ""),
    ],
)
def test_create_rejects_bad_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str, value: Any
) -> None:
    """POST /schedules answers 422 naming each invalid field."""
    app = _app(tmp_path, monkeypatch)
    resp = _request(app, "POST", "/api/schedules", json={**_VALID, field: value})
    assert resp.status_code == 422
    assert field in resp.json()["error"].lower()


def test_list_shows_next_fire_at(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /schedules lists created schedules with a computed next_fire_at."""
    app = _app(tmp_path, monkeypatch)
    created = _request(app, "POST", "/api/schedules", json=_VALID).json()
    resp = _request(app, "GET", "/api/schedules")
    assert resp.status_code == 200
    rows = resp.json()["schedules"]
    assert len(rows) == 1
    assert rows[0]["id"] == created["id"]
    assert rows[0]["next_fire_at"] is not None


def test_detail_has_upcoming_and_enriched_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GET /schedules/{id} returns 5 upcoming firings and bd-enriched runs."""
    app = _app(tmp_path, monkeypatch)
    app.state.fleet_state.queue = FakeQueue()
    created = _request(app, "POST", "/api/schedules", json=_VALID).json()
    schedule_id = created["id"]
    task_id = _request(app, "POST", f"/api/schedules/{schedule_id}/run").json()["run"]["task_id"]
    stub = _StubBeads(
        [
            {
                "id": task_id,
                "title": "Triage 1",
                "status": "open",
                "metadata": {"fleet_schedule_id": schedule_id},
            }
        ]
    )
    monkeypatch.setattr("fleet.serve.api.schedules.beads_client", stub)

    resp = _request(app, "GET", f"/api/schedules/{schedule_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["upcoming"]) == 5
    assert len(body["runs"]) == 1
    assert body["runs"][0]["task_status"] == "open"
    assert body["runs"][0]["task_title"] == "Triage 1"
    assert stub.calls[0][:2] == ["list", "--all"]
    assert f"fleet_schedule_id={schedule_id}" in stub.calls[0]


def test_detail_missing_task_maps_to_null(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Runs whose task left the beads DB enrich to null status/title."""
    app = _app(tmp_path, monkeypatch)
    app.state.fleet_state.queue = FakeQueue()
    schedule_id = _request(app, "POST", "/api/schedules", json=_VALID).json()["id"]
    _request(app, "POST", f"/api/schedules/{schedule_id}/run")
    monkeypatch.setattr("fleet.serve.api.schedules.beads_client", _StubBeads([]))

    body = _request(app, "GET", f"/api/schedules/{schedule_id}").json()
    assert body["runs"][0]["task_status"] is None
    assert body["runs"][0]["task_title"] is None


def test_detail_unknown_is_404(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /schedules/{id} answers 404 for an unknown id."""
    app = _app(tmp_path, monkeypatch)
    resp = _request(app, "GET", "/api/schedules/sch-ffffff")
    assert resp.status_code == 404


def test_put_keeps_id_and_created_at(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """PUT rewrites the body but keeps id/created_at and bumps updated_at."""
    app = _app(tmp_path, monkeypatch)
    created = _request(app, "POST", "/api/schedules", json=_VALID).json()
    schedule_id = created["id"]
    resp = _request(app, "PUT", f"/api/schedules/{schedule_id}", json={**_VALID, "title": "New"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == schedule_id
    assert body["created_at"] == created["created_at"]
    assert body["updated_at"] >= created["updated_at"]
    assert body["title"] == "New"


def test_put_unknown_is_404(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """PUT answers 404 for an unknown id."""
    app = _app(tmp_path, monkeypatch)
    resp = _request(app, "PUT", "/api/schedules/sch-ffffff", json=_VALID)
    assert resp.status_code == 404


def test_delete_removes_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """DELETE removes the definition (and history) and further reads 404."""
    app = _app(tmp_path, monkeypatch)
    app.state.fleet_state.queue = FakeQueue()
    schedule_id = _request(app, "POST", "/api/schedules", json=_VALID).json()["id"]
    _request(app, "POST", f"/api/schedules/{schedule_id}/run")
    resp = _request(app, "DELETE", f"/api/schedules/{schedule_id}")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert list(_schedules_dir(tmp_path).glob(f"{schedule_id}*")) == []
    assert _request(app, "GET", f"/api/schedules/{schedule_id}").status_code == 404


def test_run_now_appends_manual_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """POST /schedules/{id}/run opens a task via the queue and records the run."""
    app = _app(tmp_path, monkeypatch)
    app.state.fleet_state.queue = FakeQueue()
    schedule_id = _request(app, "POST", "/api/schedules", json=_VALID).json()["id"]
    resp = _request(app, "POST", f"/api/schedules/{schedule_id}/run")
    assert resp.status_code == 200
    run = resp.json()["run"]
    assert run["trigger"] == "manual"
    assert run["skipped"] is False
    assert run["task_id"] is not None
    assert run["task_status"] == "open"
    history = list(_schedules_dir(tmp_path).glob(f"{schedule_id}.runs.jsonl"))
    assert len(history) == 1
    assert "manual" in history[0].read_text(encoding="utf-8")


def test_run_unknown_is_404(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """POST /schedules/{id}/run answers 404 for an unknown id."""
    app = _app(tmp_path, monkeypatch)
    assert _request(app, "POST", "/api/schedules/sch-ffffff/run").status_code == 404


def test_preview_valid_and_invalid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """POST /schedules/preview answers 200 for good and bad expressions alike."""
    app = _app(tmp_path, monkeypatch)
    good = _request(
        app,
        "POST",
        "/api/schedules/preview",
        json={"cron": "0 9 * * 1-5", "timezone": "UTC", "count": 3},
    )
    assert good.status_code == 200
    assert good.json()["valid"] is True
    assert len(good.json()["upcoming"]) == 3
    bad = _request(app, "POST", "/api/schedules/preview", json={"cron": "nope"})
    assert bad.status_code == 200
    assert bad.json()["valid"] is False
    assert bad.json()["error"]
    assert bad.json()["upcoming"] == []


def test_disable_then_list_shows_disabled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """POST /schedules/{id}/disable flips enabled off; enable flips it back."""
    app = _app(tmp_path, monkeypatch)
    schedule_id = _request(app, "POST", "/api/schedules", json=_VALID).json()["id"]
    assert _request(app, "POST", f"/api/schedules/{schedule_id}/disable").json() == {"ok": True}
    rows = _request(app, "GET", "/api/schedules").json()["schedules"]
    assert rows[0]["enabled"] is False
    assert rows[0]["next_fire_at"] is None
    assert _request(app, "POST", f"/api/schedules/{schedule_id}/enable").json() == {"ok": True}
    rows = _request(app, "GET", "/api/schedules").json()["schedules"]
    assert rows[0]["enabled"] is True
    assert rows[0]["next_fire_at"] is not None


_WORKFLOW_BODY = {
    "name": "nightly-flow",
    "cron": "* * * * *",
    "timezone": "UTC",
    "enabled": True,
    "target": "workflow",
    "workflow_id": "wf-test0001",
    "overlap": "skip",
}


def _save_workflow(tmp_path: Path) -> None:
    """Seed one one-step workflow the schedules tests can target."""
    store = WorkflowStore(tmp_path / "workflows.db")
    store.save(
        Workflow(
            id="wf-test0001",
            name="nightly",
            description="d",
            defaults=Defaults(priority=2),
            stages=(Stage(name="checks", steps=(Step(name="lint", title="Lint"),)),),
            created_at="2026-09-09T00:00:00+00:00",
            updated_at="2026-09-09T00:00:00+00:00",
        )
    )


def test_create_workflow_schedule_needs_no_title(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """POST /schedules accepts a workflow target without a task title."""
    _save_workflow(tmp_path)
    app = _app(tmp_path, monkeypatch)
    resp = _request(app, "POST", "/api/schedules", json=_WORKFLOW_BODY)
    assert resp.status_code == 201
    body = resp.json()
    assert body["target"] == "workflow"
    assert body["workflow_id"] == "wf-test0001"


def test_create_workflow_schedule_unknown_workflow_is_422(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """POST /schedules answers 422 naming workflow_id for a missing workflow."""
    app = _app(tmp_path, monkeypatch)
    resp = _request(app, "POST", "/api/schedules", json=_WORKFLOW_BODY)
    assert resp.status_code == 422
    assert "workflow_id" in resp.json()["error"].lower()


def test_run_workflow_schedule_returns_workflow_run_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """POST /schedules/{id}/run starts a workflow run and returns its id."""
    _save_workflow(tmp_path)
    app = _app(tmp_path, monkeypatch)
    app.state.fleet_state.queue = FakeQueue()
    schedule_id = _request(app, "POST", "/api/schedules", json=_WORKFLOW_BODY).json()["id"]
    resp = _request(app, "POST", f"/api/schedules/{schedule_id}/run")
    assert resp.status_code == 200
    run = resp.json()["run"]
    assert run["task_id"] is None
    assert run["workflow_run_id"] is not None
    assert run["workflow_run_status"] == "running"


def test_list_filters_by_target(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /schedules?target= narrows to workflow or task schedules."""
    _save_workflow(tmp_path)
    app = _app(tmp_path, monkeypatch)
    _request(app, "POST", "/api/schedules", json=_VALID)
    _request(app, "POST", "/api/schedules", json=_WORKFLOW_BODY)
    assert len(_request(app, "GET", "/api/schedules").json()["schedules"]) == 2
    workflows = _request(app, "GET", "/api/schedules?target=workflow").json()["schedules"]
    assert [row["target"] for row in workflows] == ["workflow"]
    tasks = _request(app, "GET", "/api/schedules?target=task").json()["schedules"]
    assert [row["target"] for row in tasks] == ["task"]
    bad = _request(app, "GET", "/api/schedules?target=fleet")
    assert bad.status_code == 422


def test_detail_enriches_workflow_run_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GET /schedules/{id} carries the live workflow run status on each run."""
    _save_workflow(tmp_path)
    app = _app(tmp_path, monkeypatch)
    app.state.fleet_state.queue = FakeQueue()
    schedule_id = _request(app, "POST", "/api/schedules", json=_WORKFLOW_BODY).json()["id"]
    _request(app, "POST", f"/api/schedules/{schedule_id}/run")
    body = _request(app, "GET", f"/api/schedules/{schedule_id}").json()
    assert len(body["runs"]) == 1
    assert body["runs"][0]["workflow_run_id"] is not None
    assert body["runs"][0]["workflow_run_status"] == "running"
