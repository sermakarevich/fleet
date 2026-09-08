"""Tests for GET /api/tasks/{id}/children (observer Children panel)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from fleet.serve.app import create_app


def _get(app, path: str) -> httpx.Response:
    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get(path)

    return asyncio.run(_run())


def test_children_endpoint_reports_status_and_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    tasks_root = tmp_path / "tasks"
    epic_dir = tasks_root / "epic-1"
    (epic_dir / "artifacts").mkdir(parents=True)
    (epic_dir / "task.json").write_text(json.dumps({"id": "epic-1", "status": "open"}))
    (epic_dir / "artifacts" / "CHILDREN.md").write_text("# Children digest\n\n## c-1")
    child_dir = tasks_root / "c-1"
    (child_dir / "artifacts").mkdir(parents=True)
    (child_dir / "artifacts" / "RESULT.json").write_text(
        json.dumps({"schema": 1, "status": "done", "summary": "shipped"})
    )
    monkeypatch.setattr(
        "fleet.serve.api.tasks_detail.beads_client.children_of",
        lambda epic_id, home: [{"id": "c-1", "title": "Kid", "status": "closed"}],
    )
    resp = _get(create_app(), "/api/tasks/epic-1/children")
    assert resp.status_code == 200
    body = resp.json()
    assert body["children"] == [
        {
            "id": "c-1",
            "title": "Kid",
            "status": "closed",
            "result_status": "done",
            "result_summary": "shipped",
        }
    ]
    assert body["children_md"] == "# Children digest\n\n## c-1"


def test_children_endpoint_404_without_task_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    resp = _get(create_app(), "/api/tasks/ghost/children")
    assert resp.status_code == 404
