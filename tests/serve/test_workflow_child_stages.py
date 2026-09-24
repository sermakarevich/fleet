"""Run-detail `child_stages`: a job epic's `summarise`/`aggregate` columns.

Covers `serve/api/workflows.py::_run_detail` attaching `child_stages` built
from the step task dir's `tasks.json` design plus `children.json` /
`children_skipped.json` journals: a research-shaped design groups into two
stages with the right statuses, and a step with no `tasks.json` (a plain
step, or a job epic before spawn) leaves `child_stages` empty.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from fleet.core.job_ready import BeadSummary
from fleet.serve.app import create_app
from tests.conftest import FakeQueue


def _valid(tmp_path: Path, name: str = "research-flow") -> dict[str, Any]:
    """A small valid workflow body with an existing cwd."""
    return {
        "name": name,
        "description": "d",
        "defaults": {"cwd": str(tmp_path), "coder": "claude", "priority": 2},
        "stages": [
            {
                "name": "research",
                "steps": [
                    {"name": "epic", "title": "Research epic", "description": "Spawn children."},
                ],
            },
        ],
    }


def _app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, queue: FakeQueue | None = None):
    """Serve app against a throwaway fleet home with a fake queue."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    app = create_app()
    app.state.fleet_state.queue = queue if queue is not None else FakeQueue()
    return app


def _request(app, method: str, path: str, **kwargs: Any) -> httpx.Response:
    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.request(method, path, **kwargs)

    return asyncio.run(_run())


def _start(app, tmp_path: Path, name: str) -> dict[str, Any]:
    """Create a workflow and start one run, returning the run payload."""
    workflow_id = _request(app, "POST", "/api/workflows", json=_valid(tmp_path, name)).json()["id"]
    resp = _request(app, "POST", f"/api/workflows/{workflow_id}/run")
    assert resp.status_code == 201
    return resp.json()["run"]


def _artifacts(tmp_path: Path, task_id: str) -> Path:
    """The step task dir's artifacts directory, created."""
    artifacts = tmp_path / "tasks" / task_id / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    return artifacts


def test_detail_includes_child_stages_from_research_design(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A research epic's tasks.json/children journals become two stages."""
    queue = FakeQueue()
    app = _app(tmp_path, monkeypatch, queue)
    parent = _start(app, tmp_path, "research-flow")
    child = _start(app, tmp_path, "child-flow")
    step_task = parent["steps"][0]["task_id"]

    artifacts = _artifacts(tmp_path, step_task)
    (artifacts / "tasks.json").write_text(
        json.dumps(
            {
                "tasks": [
                    {"key": "src-01", "title": "summarise: Paper One", "workflow": "summarise"},
                    {"key": "src-02", "title": "summarise: Paper Two", "workflow": "summarise"},
                    {"key": "topic-01", "title": "digest: code-generation"},
                    {"key": "agg-index", "title": "index.md"},
                ]
            }
        ),
        encoding="utf-8",
    )
    (artifacts / "children.json").write_text(
        json.dumps({"src-02": child["id"], "topic-01": "fleet-topic1", "agg-index": "fleet-index"}),
        encoding="utf-8",
    )
    (artifacts / "children_skipped.json").write_text(
        json.dumps({"src-01": "HTTP Error 406: Not Acceptable"}), encoding="utf-8"
    )
    queue._children[step_task] = [
        BeadSummary(id="fleet-topic1", status="closed", title="digest: code-generation"),
        BeadSummary(id="fleet-index", status="open", title="index.md"),
    ]

    detail = _request(app, "GET", f"/api/workflow-runs/{parent['id']}")
    assert detail.status_code == 200
    stages = detail.json()["child_stages"]
    assert [stage["title"] for stage in stages] == ["summarise", "aggregate"]

    summarise = {item["key"]: item for item in stages[0]["items"]}
    assert summarise["src-01"]["status"] == "skipped"
    assert summarise["src-01"]["reason"] == "HTTP Error 406: Not Acceptable"
    assert summarise["src-02"]["status"] == child["status"]
    assert summarise["src-02"]["ref"] == child["id"]

    aggregate = {item["key"]: item for item in stages[1]["items"]}
    assert aggregate["topic-01"]["status"] == "closed"
    assert aggregate["agg-index"]["status"] == "open"


def test_detail_without_tasks_json_leaves_child_stages_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A plain step (or a job epic before spawn) has no tasks.json: no child_stages."""
    app = _app(tmp_path, monkeypatch)
    parent = _start(app, tmp_path, "research-flow")

    detail = _request(app, "GET", f"/api/workflow-runs/{parent['id']}")
    assert detail.status_code == 200
    assert detail.json()["child_stages"] == []
