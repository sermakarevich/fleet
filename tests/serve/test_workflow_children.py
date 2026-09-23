"""Run-detail children: job-spawned child runs and plain beads per step.

Covers `serve/api/workflows.py::_run_detail` reading the step task dir's
`children_runs.json` / `children.json` journals: populated children from
fixture artifacts, empty (never an error) for missing/corrupt artifacts or
a failing queue, an `unknown` row for a journaled run the store forgot,
empty children on the cheap list routes, and parent ids on the run view.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from fleet.beads.client import BdError
from fleet.core.job_ready import BeadSummary
from fleet.serve.app import create_app
from tests.conftest import FakeQueue


def _valid(tmp_path: Path, name: str = "parent-flow") -> dict[str, Any]:
    """A small valid workflow body with an existing cwd."""
    return {
        "name": name,
        "description": "d",
        "defaults": {"cwd": str(tmp_path), "coder": "claude", "priority": 2},
        "stages": [
            {
                "name": "stage-one",
                "steps": [
                    {"name": "epic", "title": "Job epic", "description": "Spawn children."},
                ],
            },
        ],
    }


class FailingChildrenQueue(FakeQueue):
    """FakeQueue whose child listing fails like an unreachable bd."""

    def list_children(self, epic_id: str) -> list[BeadSummary]:
        raise BdError("bd is down")


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


def test_detail_populates_children_from_journals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Journaled child runs and plain beads show on the step with progress."""
    queue = FakeQueue()
    app = _app(tmp_path, monkeypatch, queue)
    parent = _start(app, tmp_path, "parent-flow")
    child = _start(app, tmp_path, "child-flow")
    step_task = parent["steps"][0]["task_id"]

    store = app.state.fleet_state.workflow_store
    child_steps = store.step_runs(child["id"])
    assert len(child_steps) == 1
    store.update_step_status(child["id"], "epic", "closed", "2026-09-09T02:00:00Z")

    (_artifacts(tmp_path, step_task) / "children_runs.json").write_text(
        json.dumps(
            {
                "src-01": {
                    "run_id": child["id"],
                    "task_ids": [s.task_id for s in child_steps],
                    "final_task_ids": [s.task_id for s in child_steps],
                }
            }
        ),
        encoding="utf-8",
    )
    (_artifacts(tmp_path, step_task) / "children.json").write_text(
        json.dumps({"src-01": child["id"], "t-01": "fleet-plain1"}), encoding="utf-8"
    )
    queue._children[step_task] = [
        BeadSummary(id="fleet-plain1", status="open", title="Plain child")
    ]

    detail = _request(app, "GET", f"/api/workflow-runs/{parent['id']}")
    assert detail.status_code == 200
    children = detail.json()["steps"][0]["children"]
    assert children["runs"] == [
        {
            "key": "src-01",
            "run_id": child["id"],
            "workflow_name": "child-flow",
            "status": child["status"],
            "steps_done": 1,
            "steps_total": 1,
        }
    ]
    assert children["beads"] == [
        {"key": "t-01", "id": "fleet-plain1", "title": "Plain child", "status": "open"}
    ]
    # The workflow child journaled under children.json is not a plain bead.
    assert [bead["id"] for bead in children["beads"]] == ["fleet-plain1"]
    # Runs without parents stay parentless.
    assert detail.json()["parent_run_id"] is None
    assert detail.json()["parent_task_id"] is None


def test_detail_missing_artifacts_means_empty_children(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No journals on disk: empty children, still 200."""
    app = _app(tmp_path, monkeypatch)
    parent = _start(app, tmp_path, "parent-flow")

    detail = _request(app, "GET", f"/api/workflow-runs/{parent['id']}")
    assert detail.status_code == 200
    assert detail.json()["steps"][0]["children"] == {"runs": [], "beads": []}


def test_detail_corrupt_artifacts_means_empty_children(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unparseable journals: empty children, still 200."""
    app = _app(tmp_path, monkeypatch)
    parent = _start(app, tmp_path, "parent-flow")
    step_task = parent["steps"][0]["task_id"]

    (_artifacts(tmp_path, step_task) / "children_runs.json").write_text(
        "not json{", encoding="utf-8"
    )
    (_artifacts(tmp_path, step_task) / "children.json").write_text("[1, 2]", encoding="utf-8")

    detail = _request(app, "GET", f"/api/workflow-runs/{parent['id']}")
    assert detail.status_code == 200
    assert detail.json()["steps"][0]["children"] == {"runs": [], "beads": []}


def test_detail_unknown_child_run_is_unknown_not_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A journaled run id the store never saw still shows, marked unknown."""
    app = _app(tmp_path, monkeypatch)
    parent = _start(app, tmp_path, "parent-flow")
    step_task = parent["steps"][0]["task_id"]

    (_artifacts(tmp_path, step_task) / "children_runs.json").write_text(
        json.dumps({"src-09": {"run_id": "wfr-vanished"}}), encoding="utf-8"
    )

    detail = _request(app, "GET", f"/api/workflow-runs/{parent['id']}")
    assert detail.status_code == 200
    assert detail.json()["steps"][0]["children"]["runs"] == [
        {
            "key": "src-09",
            "run_id": "wfr-vanished",
            "workflow_name": None,
            "status": "unknown",
            "steps_done": 0,
            "steps_total": 0,
        }
    ]


def test_detail_queue_failure_means_empty_beads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """list_children raising (bd down): child runs still show, beads empty."""
    app = _app(tmp_path, monkeypatch, FailingChildrenQueue())
    parent = _start(app, tmp_path, "parent-flow")
    child = _start(app, tmp_path, "child-flow")
    step_task = parent["steps"][0]["task_id"]

    (_artifacts(tmp_path, step_task) / "children_runs.json").write_text(
        json.dumps({"src-01": {"run_id": child["id"]}}), encoding="utf-8"
    )
    (_artifacts(tmp_path, step_task) / "children.json").write_text(
        json.dumps({"t-01": "fleet-plain1"}), encoding="utf-8"
    )

    detail = _request(app, "GET", f"/api/workflow-runs/{parent['id']}")
    assert detail.status_code == 200
    children = detail.json()["steps"][0]["children"]
    assert [run["run_id"] for run in children["runs"]] == [child["id"]]
    assert children["beads"] == []


def test_list_routes_leave_children_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The runs lists never read journals: children stay empty there."""
    queue = FakeQueue()
    app = _app(tmp_path, monkeypatch, queue)
    parent = _start(app, tmp_path, "parent-flow")
    child = _start(app, tmp_path, "child-flow")
    step_task = parent["steps"][0]["task_id"]

    (_artifacts(tmp_path, step_task) / "children_runs.json").write_text(
        json.dumps({"src-01": {"run_id": child["id"]}}), encoding="utf-8"
    )

    listed = _request(app, "GET", "/api/workflow-runs")
    assert listed.status_code == 200
    assert listed.json()["runs"][0]["steps"][0]["children"] == {"runs": [], "beads": []}

    workflows = _request(app, "GET", "/api/workflows")
    assert workflows.status_code == 200
    last = workflows.json()["workflows"][0]["last_run"]
    assert last is not None and last["steps"][0]["children"] == {"runs": [], "beads": []}
