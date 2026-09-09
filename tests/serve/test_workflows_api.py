"""Tests for the /api/workflows REST routes (WF 3/8, ADR 0008)."""

from __future__ import annotations

import asyncio
import shlex
from pathlib import Path
from typing import Any

import httpx
import pytest

from fleet.serve.app import create_app
from fleet.workflows.yaml_io import from_yaml
from tests.conftest import FakeQueue


def _valid(tmp_path: Path) -> dict[str, Any]:
    """A small valid workflow body with an existing cwd."""
    return {
        "name": "nightly-quality",
        "description": "Lint, test and summarise",
        "defaults": {"cwd": str(tmp_path), "coder": "claude", "priority": 2},
        "stages": [
            {
                "name": "checks",
                "steps": [
                    {"name": "lint", "title": "Lint it", "description": "Run ruff."},
                    {"name": "tests", "title": "Run tests", "description": "Run pytest."},
                ],
            },
            {
                "name": "report",
                "steps": [
                    {
                        "name": "summary",
                        "title": "Summarise the night",
                        "description": "Write up.",
                    },
                ],
            },
        ],
    }


_ADR_YAML = """\
fleet_workflow: 1
name: nightly-quality
description: Lint, test and summarise
defaults: {coder: opencode, priority: 2}
stages:
  - name: checks
    steps:
      - name: lint
        title: "Lint {{workflow.name}} ({{run.date}})"
        description: Run ruff and fix what it reports.
      - name: tests
        title: Run the test suite
        description: uv run pytest -q; fix failures.
        coder: claude
        model: sonnet
  - name: report
    steps:
      - name: summary
        title: Summarise the night
        description: "Read tasks {{steps.lint.task_id}} and {{steps.tests.task_id}}."
        needs: [lint, tests]
"""


class RecordingQueue(FakeQueue):
    """FakeQueue that remembers every create_task call and its task id."""

    def __init__(self) -> None:
        super().__init__()
        self.creates: list[dict] = []

    def create_task(  # noqa: PLR0913, PLR0917  # mirrors Queue.create_task signature
        self,
        title: str,
        description: str | None = None,
        depends_on: list[str] | None = None,
        labels: list[str] | None = None,
        cwd: str | None = None,
        coder: str | None = None,
        model: str | None = None,
        worker: str | None = None,
        extra_args: str | None = None,
    ):  # type: ignore[no-untyped-def]
        task = super().create_task(
            title, description, depends_on, labels, cwd, coder, model, worker, extra_args
        )
        self.creates.append({"id": task.id, "title": title, "extra_args": extra_args or ""})
        return task


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


def test_create_returns_201_and_get_returns_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """POST /workflows answers 201 and GET returns the same definition."""
    app = _app(tmp_path, monkeypatch)
    resp = _request(app, "POST", "/api/workflows", json=_valid(tmp_path))
    assert resp.status_code == 201
    body = resp.json()
    assert body["id"].startswith("wf-")
    assert body["name"] == "nightly-quality"
    assert body["step_count"] == 3
    assert body["stage_count"] == 2
    assert body["run_count"] == 0
    assert body["last_run"] is None

    fetched = _request(app, "GET", f"/api/workflows/{body['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == body["id"]
    assert fetched.json()["stages"][0]["steps"][0]["name"] == "lint"

    listed = _request(app, "GET", "/api/workflows")
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["workflows"]] == [body["id"]]


def test_create_invalid_needs_answers_422_with_problem_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A step needing a later-stage step is 422 naming the problem."""
    app = _app(tmp_path, monkeypatch)
    payload = _valid(tmp_path)
    payload["stages"][0]["steps"][0]["needs"] = ["summary"]
    resp = _request(app, "POST", "/api/workflows", json=payload)
    assert resp.status_code == 422
    assert "same or a later stage" in resp.json()["error"]


def test_create_rejects_unknown_coder_and_missing_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unknown coder names and missing cwds are 422 naming the field."""
    app = _app(tmp_path, monkeypatch)
    bad_coder = _valid(tmp_path)
    bad_coder["defaults"]["coder"] = "nope-coder"
    resp = _request(app, "POST", "/api/workflows", json=bad_coder)
    assert resp.status_code == 422
    assert "coder" in resp.json()["error"].lower()

    bad_cwd = _valid(tmp_path)
    bad_cwd["defaults"]["cwd"] = "/does/not/exist"
    resp = _request(app, "POST", "/api/workflows", json=bad_cwd)
    assert resp.status_code == 422
    assert "cwd" in resp.json()["error"].lower()


def test_validate_returns_problems_with_200(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """POST /workflows/validate never 4xx: bad content is valid=false."""
    app = _app(tmp_path, monkeypatch)
    good = _request(app, "POST", "/api/workflows/validate", json=_valid(tmp_path))
    assert good.status_code == 200
    assert good.json() == {"valid": True, "problems": []}

    payload = _valid(tmp_path)
    payload["stages"][0]["steps"][0]["needs"] = ["ghost"]
    bad = _request(app, "POST", "/api/workflows/validate", json=payload)
    assert bad.status_code == 200
    assert bad.json()["valid"] is False
    assert any("ghost" in problem for problem in bad.json()["problems"])


def test_import_export_round_trip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Import the ADR example (201), export it back, parse both to the same shape."""
    app = _app(tmp_path, monkeypatch)
    resp = _request(app, "POST", "/api/workflows/import", json={"yaml": _ADR_YAML})
    assert resp.status_code == 201
    workflow_id = resp.json()["id"]
    assert resp.json()["name"] == "nightly-quality"

    exported = _request(app, "GET", f"/api/workflows/{workflow_id}/export")
    assert exported.status_code == 200
    yaml_text = exported.json()["yaml"]
    assert from_yaml(yaml_text).to_dict()["stages"] == from_yaml(_ADR_YAML).to_dict()["stages"]

    text = _request(app, "GET", f"/api/workflows/{workflow_id}/export?format=text")
    assert text.status_code == 200
    assert "attachment; filename=nightly-quality.yaml" in text.headers["content-disposition"]
    assert from_yaml(text.text).name == "nightly-quality"


def test_import_name_clash_is_409_replace_keeps_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A second import of the same name is 409; replace_id rewrites in place."""
    app = _app(tmp_path, monkeypatch)
    first = _request(app, "POST", "/api/workflows/import", json={"yaml": _ADR_YAML})
    assert first.status_code == 201
    clash = _request(app, "POST", "/api/workflows/import", json={"yaml": _ADR_YAML})
    assert clash.status_code == 409

    replaced = _request(
        app,
        "POST",
        "/api/workflows/import",
        json={"yaml": _ADR_YAML, "replace_id": first.json()["id"]},
    )
    assert replaced.status_code == 201
    assert replaced.json()["id"] == first.json()["id"]

    unknown = _request(
        app, "POST", "/api/workflows/import", json={"yaml": _ADR_YAML, "replace_id": "wf-ffffff"}
    )
    assert unknown.status_code == 404


def test_run_creates_tasks_with_deps_lists_and_detail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """POST /run opens beads with --deps; lists and detail show the run."""
    queue = RecordingQueue()
    app = _app(tmp_path, monkeypatch, queue)
    workflow_id = _request(app, "POST", "/api/workflows", json=_valid(tmp_path)).json()["id"]

    resp = _request(app, "POST", f"/api/workflows/{workflow_id}/run")
    assert resp.status_code == 201
    run = resp.json()["run"]
    assert run["status"] == "running"
    assert run["n"] == 1
    assert [step["step_name"] for step in run["steps"]] == ["lint", "tests", "summary"]

    first_ids = [queue.creates[0]["id"], queue.creates[1]["id"]]
    tokens = shlex.split(queue.creates[2]["extra_args"])
    assert tokens[tokens.index("--deps") + 1] == ",".join(first_ids)
    assert "--deps" not in shlex.split(queue.creates[0]["extra_args"])

    per_workflow = _request(app, "GET", f"/api/workflows/{workflow_id}/runs")
    assert per_workflow.status_code == 200
    assert per_workflow.json()["total"] == 1

    filtered = _request(app, "GET", "/api/workflow-runs?status=running")
    assert filtered.status_code == 200
    assert filtered.json()["total"] == 1
    assert _request(app, "GET", "/api/workflow-runs?status=succeeded").json()["total"] == 0

    detail = _request(app, "GET", f"/api/workflow-runs/{run['id']}")
    assert detail.status_code == 200
    assert detail.json()["steps"][0]["task_title"] == "Lint it"

    listed = _request(app, "GET", "/api/workflows")
    assert listed.json()["workflows"][0]["run_count"] == 1
    assert listed.json()["workflows"][0]["last_run"]["id"] == run["id"]


def test_cancel_marks_run_cancelled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """POST /workflow-runs/{id}/cancel closes the beads and marks the run."""
    app = _app(tmp_path, monkeypatch)
    workflow_id = _request(app, "POST", "/api/workflows", json=_valid(tmp_path)).json()["id"]
    run_id = _request(app, "POST", f"/api/workflows/{workflow_id}/run").json()["run"]["id"]

    resp = _request(app, "POST", f"/api/workflow-runs/{run_id}/cancel")
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"

    detail = _request(app, "GET", f"/api/workflow-runs/{run_id}")
    assert detail.json()["status"] == "cancelled"


def test_delete_while_running_is_409_then_ok_after_cancel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DELETE refuses 409 while a run runs; after cancel it removes the workflow."""
    app = _app(tmp_path, monkeypatch)
    workflow_id = _request(app, "POST", "/api/workflows", json=_valid(tmp_path)).json()["id"]
    run_id = _request(app, "POST", f"/api/workflows/{workflow_id}/run").json()["run"]["id"]

    busy = _request(app, "DELETE", f"/api/workflows/{workflow_id}")
    assert busy.status_code == 409

    _request(app, "POST", f"/api/workflow-runs/{run_id}/cancel")
    removed = _request(app, "DELETE", f"/api/workflows/{workflow_id}")
    assert removed.status_code == 200
    assert removed.json() == {"ok": True}
    assert _request(app, "GET", f"/api/workflows/{workflow_id}").status_code == 404


def test_unknown_ids_are_404(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Unknown workflow and run ids answer 404 on every read route."""
    app = _app(tmp_path, monkeypatch)
    assert _request(app, "GET", "/api/workflows/wf-ffffff").status_code == 404
    assert (
        _request(app, "PUT", "/api/workflows/wf-ffffff", json=_valid(tmp_path)).status_code == 404
    )
    assert _request(app, "DELETE", "/api/workflows/wf-ffffff").status_code == 404
    assert _request(app, "GET", "/api/workflows/wf-ffffff/export").status_code == 404
    assert _request(app, "POST", "/api/workflows/wf-ffffff/run").status_code == 404
    assert _request(app, "GET", "/api/workflows/wf-ffffff/runs").status_code == 404
    assert _request(app, "GET", "/api/workflow-runs/wfr-ffffff").status_code == 404
    assert _request(app, "POST", "/api/workflow-runs/wfr-ffffff/cancel").status_code == 404


def test_put_keeps_id_and_created_at(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """PUT rewrites the definition but keeps id/created_at and bumps updated_at."""
    app = _app(tmp_path, monkeypatch)
    created = _request(app, "POST", "/api/workflows", json=_valid(tmp_path)).json()
    payload = _valid(tmp_path)
    payload["description"] = "new description"
    resp = _request(app, "PUT", f"/api/workflows/{created['id']}", json=payload)
    assert resp.status_code == 200
    assert resp.json()["id"] == created["id"]
    assert resp.json()["created_at"] == created["created_at"]
    assert resp.json()["updated_at"] >= created["updated_at"]
    assert resp.json()["description"] == "new description"
