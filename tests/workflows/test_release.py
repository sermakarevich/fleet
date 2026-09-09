"""Release tests: late rendering of deferred steps once dependencies close.

Covers the WI 2/3 refresh flow against FakeQueue plus a throwaway
WorkflowStore: outputs.json collection, deferred release with rendered
text, waiting on open dependencies, missing-output warnings, and cancel
closing deferred beads. No test ever touches the real `bd` binary.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from pathlib import Path

from fleet.core.task import Task
from fleet.workflows.model import (
    Defaults,
    RunStatus,
    Stage,
    Step,
    Trigger,
    Workflow,
)
from fleet.workflows.runs import (
    cancel_run,
    refresh_run,
    refresh_run_with_tasks,
    start_run,
)
from fleet.workflows.store import WorkflowStore
from tests.conftest import FakeQueue


def _at(raw: str) -> datetime:
    """Parse one test timestamp as aware UTC."""
    return datetime.fromisoformat(raw)


def _workflow() -> Workflow:
    """Two stages: stage 2 quotes a value stage 1 publishes via outputs.json."""
    return Workflow(
        id="wf-outputs001",
        name="pipe",
        description="d",
        defaults=Defaults(priority=2),
        stages=(
            Stage(name="first", steps=(Step(name="fetch", title="Fetch"),)),
            Stage(
                name="second",
                steps=(
                    Step(
                        name="publish",
                        title="Post {{steps.fetch.outputs.slug}}",
                        description="Folder {{steps.fetch.outputs.paper_dir}} "
                        "by {{steps.fetch.task_id}}.",
                    ),
                ),
            ),
        ),
    )


def _store(tmp_path: Path) -> WorkflowStore:
    """Throwaway store with the outputs workflow saved."""
    store = WorkflowStore(tmp_path / "workflows.db")
    store.save(
        replace(
            _workflow(),
            created_at="2026-09-09T00:00:00+00:00",
            updated_at="2026-09-09T00:00:00+00:00",
        )
    )
    return store


def _write_outputs(fleet_home: Path, task_id: str, payload: str) -> None:
    """Drop an outputs.json into a fake task dir, like a worker would."""
    task_dir = fleet_home / "tasks" / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / "outputs.json").write_text(payload, encoding="utf-8")


def _defer(queue: FakeQueue, task_id: str) -> None:
    """Park one fake task deferred, like `bd create --defer` does."""
    task: Task = queue.get(task_id)
    queue._tasks[task_id] = replace(task, status="deferred")


def _start(queue: FakeQueue, tmp_path: Path):
    """Start one outputs run; return (run, fetch_id, publish_id)."""
    run = start_run(
        _workflow(),
        store=_store(tmp_path),
        queue=queue,
        now=_at("2026-09-09T02:00:00+00:00"),
        trigger=Trigger.manual,
    )
    return run, queue.created[0]["id"], queue.created[1]["id"]


def test_refresh_releases_step_with_outputs(tmp_path: Path) -> None:
    queue = FakeQueue()
    store = _store(tmp_path)
    run, fetch_id, publish_id = _start(queue, tmp_path)
    _defer(queue, publish_id)
    _write_outputs(tmp_path, fetch_id, '{"slug": "x", "paper_dir": "/tmp/x"}')
    queue.close(fetch_id, "done")

    refreshed, _ = refresh_run_with_tasks(
        run, store=store, queue=queue, now=_at("2026-09-09T02:30:00+00:00")
    )
    assert refreshed.status is RunStatus.running
    steps = {item.step_name: item for item in store.step_runs(run.id)}
    assert steps["fetch"].outputs == {"slug": "x", "paper_dir": "/tmp/x"}
    assert steps["publish"].released is True
    assert steps["publish"].warning is None
    published = queue.get(publish_id)
    assert published.status == "open"
    assert published.title == "Post x"
    assert published.description == f"Folder /tmp/x by {fetch_id}."
    assert queue.updated[-1] == {
        "id": publish_id,
        "title": "Post x",
        "description": f"Folder /tmp/x by {fetch_id}.",
        "undefer": True,
    }


def test_refresh_waits_for_dependencies(tmp_path: Path) -> None:
    queue = FakeQueue()
    store = _store(tmp_path)
    run, _, publish_id = _start(queue, tmp_path)
    _defer(queue, publish_id)
    refresh_run(run, store=store, queue=queue, now=_at("2026-09-09T02:30:00+00:00"))
    assert store.step_runs(run.id)[1].released is False
    assert queue.updated == []
    assert queue.get(publish_id).status == "deferred"


def test_refresh_missing_output_renders_empty_and_warns(tmp_path: Path) -> None:
    queue = FakeQueue()
    store = _store(tmp_path)
    run, fetch_id, publish_id = _start(queue, tmp_path)
    _defer(queue, publish_id)
    _write_outputs(tmp_path, fetch_id, '{"other": "1"}')
    queue.close(fetch_id, "done")

    refresh_run(run, store=store, queue=queue, now=_at("2026-09-09T02:30:00+00:00"))
    steps = {item.step_name: item for item in store.step_runs(run.id)}
    assert steps["publish"].released is True
    assert steps["publish"].warning == (
        "outputs_missing: steps.fetch.outputs.paper_dir, steps.fetch.outputs.slug"
    )
    published = queue.get(publish_id)
    assert published.title == "Post "
    assert published.description == f"Folder  by {fetch_id}."


def test_cancel_run_closes_deferred_beads(tmp_path: Path) -> None:
    queue = FakeQueue()
    store = _store(tmp_path)
    run, _, publish_id = _start(queue, tmp_path)
    _defer(queue, publish_id)
    store.update_step_status(run.id, "publish", "deferred", "2026-09-09T02:10:00+00:00")
    cancelled = cancel_run(run, store=store, queue=queue, now=_at("2026-09-09T03:00:00+00:00"))
    assert cancelled.status is RunStatus.cancelled
    assert queue.get(publish_id).status == "closed"
