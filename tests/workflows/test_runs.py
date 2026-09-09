"""Run engine tests: start, refresh, and cancel against FakeQueue.

Everything runs on `FakeQueue` plus a throwaway `WorkflowStore`; no test
ever touches the real `bd` binary.
"""

from __future__ import annotations

import json
import shlex
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest

from fleet.beads.client import BdError
from fleet.core.errors import WorkflowInvalid
from fleet.core.task import Task
from fleet.workflows.model import (
    Defaults,
    RunStatus,
    Stage,
    Step,
    StepState,
    Trigger,
    Workflow,
    WorkflowInput,
)
from fleet.workflows.runs import (
    cancel_run,
    refresh_run,
    resolve_inputs,
    start_run,
    step_states,
)
from fleet.workflows.store import WorkflowStore
from tests.conftest import FakeQueue


def _at(raw: str) -> datetime:
    """Parse one test timestamp as aware UTC."""
    return datetime.fromisoformat(raw)


def _workflow() -> Workflow:
    """Two first-stage steps plus a summary that quotes both task ids."""
    return Workflow(
        id="wf-run00001",
        name="nightly",
        description="d",
        defaults=Defaults(priority=2),
        stages=(
            Stage(
                name="checks",
                steps=(
                    Step(name="lint", title="Lint {{workflow.name}}"),
                    Step(name="tests", title="Run tests"),
                ),
            ),
            Stage(
                name="report",
                steps=(
                    Step(
                        name="summary",
                        title="Summary of {{run.id}}",
                        description="Read {{steps.lint.task_id}} and {{steps.tests.task_id}}.",
                    ),
                ),
            ),
        ),
    )


def _store(tmp_path: Path) -> WorkflowStore:
    """Throwaway store with the demo workflow saved (runs need the FK row)."""
    store = WorkflowStore(tmp_path / "workflows.db")
    stamped = replace(
        _workflow(),
        created_at="2026-09-09T00:00:00+00:00",
        updated_at="2026-09-09T00:00:00+00:00",
    )
    store.save(stamped)
    return store


class RecordingQueue(FakeQueue):
    """FakeQueue that remembers every create_task call and its task id."""

    def __init__(self, tasks: list[Task] | None = None) -> None:
        super().__init__(tasks)
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
    ) -> Task:
        task = super().create_task(
            title, description, depends_on, labels, cwd, coder, model, worker, extra_args
        )
        self.creates.append(
            {
                "id": task.id,
                "title": title,
                "description": description,
                "extra_args": extra_args or "",
            }
        )
        return task


def _meta_of(extra_args: str) -> dict:
    """Decode the --metadata JSON payload from a create extra_args string."""
    tokens = shlex.split(extra_args)
    return json.loads(tokens[tokens.index("--metadata") + 1])


def test_start_run_creates_tasks_in_stage_order(tmp_path: Path) -> None:
    queue = RecordingQueue()
    run = start_run(
        _workflow(),
        store=_store(tmp_path),
        queue=queue,
        now=_at("2026-09-09T02:00:00+00:00"),
        trigger=Trigger.manual,
    )
    assert run.status is RunStatus.running
    assert run.n == 1
    assert [item["title"] for item in queue.creates] == [
        "Lint nightly",
        "Run tests",
        "Summary of {{run.id}}",
    ]


def test_start_run_defers_later_stages_unrendered(tmp_path: Path) -> None:
    store = _store(tmp_path)
    queue = RecordingQueue()
    run = start_run(
        _workflow(),
        store=store,
        queue=queue,
        now=_at("2026-09-09T02:00:00+00:00"),
        trigger=Trigger.manual,
    )
    assert "--defer" not in shlex.split(queue.creates[0]["extra_args"])
    assert "--defer" not in shlex.split(queue.creates[1]["extra_args"])
    tokens = shlex.split(queue.creates[2]["extra_args"])
    assert tokens[tokens.index("--defer") + 1] == "+30d"
    assert queue.creates[2]["description"] == (
        "Read {{steps.lint.task_id}} and {{steps.tests.task_id}}."
    )
    released = {item.step_name: item.released for item in store.step_runs(run.id)}
    assert released == {"lint": True, "tests": True, "summary": False}


def test_start_run_second_stage_depends_on_both_first_stage_ids(tmp_path: Path) -> None:
    queue = RecordingQueue()
    run = start_run(
        _workflow(),
        store=_store(tmp_path),
        queue=queue,
        now=_at("2026-09-09T02:00:00+00:00"),
        trigger=Trigger.manual,
    )
    first_ids = [queue.creates[0]["id"], queue.creates[1]["id"]]
    tokens = shlex.split(queue.creates[2]["extra_args"])
    assert tokens[tokens.index("--deps") + 1] == ",".join(first_ids)
    assert "--deps" not in shlex.split(queue.creates[0]["extra_args"])
    assert run.spec.id == "wf-run00001"


def test_start_run_labels_and_metadata_shape(tmp_path: Path) -> None:
    queue = RecordingQueue()
    run = start_run(
        _workflow(),
        store=_store(tmp_path),
        queue=queue,
        now=_at("2026-09-09T02:00:00+00:00"),
        trigger=Trigger.manual,
    )
    extra = queue.creates[0]["extra_args"]
    assert "-p 2" in extra
    for label in (f"workflow:{run.workflow_id}", f"run:{run.id}", "step:lint"):
        assert label in extra
    assert _meta_of(extra) == {
        "fleet_workflow_id": run.workflow_id,
        "fleet_workflow_run": run.id,
        "fleet_workflow_step": "lint",
    }


def test_start_run_stage_two_keeps_task_id_placeholders_for_release(tmp_path: Path) -> None:
    queue = RecordingQueue()
    start_run(
        _workflow(),
        store=_store(tmp_path),
        queue=queue,
        now=_at("2026-09-09T02:00:00+00:00"),
        trigger=Trigger.manual,
    )
    assert queue.creates[2]["description"] == (
        "Read {{steps.lint.task_id}} and {{steps.tests.task_id}}."
    )


def test_start_run_saves_step_runs_open(tmp_path: Path) -> None:
    store = _store(tmp_path)
    run = start_run(
        _workflow(),
        store=store,
        queue=RecordingQueue(),
        now=_at("2026-09-09T02:00:00+00:00"),
        trigger=Trigger.manual,
    )
    steps = store.step_runs(run.id)
    assert [(item.step_name, item.task_status) for item in steps] == [
        ("lint", "open"),
        ("tests", "open"),
        ("summary", "open"),
    ]


class FailingQueue(RecordingQueue):
    """RecordingQueue whose third create raises, like a `bd` failure."""

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
    ) -> Task:
        if len(self.creates) >= 2:
            raise BdError("boom")
        return super().create_task(
            title, description, depends_on, labels, cwd, coder, model, worker, extra_args
        )


def test_start_run_create_failure_marks_attention_keeps_steps(tmp_path: Path) -> None:
    store = _store(tmp_path)
    queue = FailingQueue()
    with pytest.raises(BdError):
        start_run(
            _workflow(),
            store=store,
            queue=queue,
            now=_at("2026-09-09T02:00:00+00:00"),
            trigger=Trigger.manual,
        )
    run_id = store.list_runs()[0].id
    run = store.get_run(run_id)
    assert run is not None and run.status is RunStatus.attention
    assert run.reason == "create failed at step summary: boom"
    assert [item.step_name for item in store.step_runs(run_id)] == ["lint", "tests"]


def test_refresh_run_moves_statuses_and_finishes_once(tmp_path: Path) -> None:
    store = _store(tmp_path)
    queue = RecordingQueue()
    run = start_run(
        _workflow(),
        store=store,
        queue=queue,
        now=_at("2026-09-09T02:00:00+00:00"),
        trigger=Trigger.manual,
    )
    assert step_states(run, store=store) == {
        "lint": StepState.waiting,
        "tests": StepState.waiting,
        "summary": StepState.waiting,
    }
    queue.close(queue.creates[0]["id"], "done")
    still_running = refresh_run(run, store=store, queue=queue, now=_at("2026-09-09T02:30:00+00:00"))
    assert still_running.status is RunStatus.running
    assert still_running.finished_at is None
    assert step_states(run, store=store)["lint"] is StepState.done
    for item in queue.creates:
        queue.close(item["id"], "done")
    done = refresh_run(run, store=store, queue=queue, now=_at("2026-09-09T03:00:00+00:00"))
    assert done.status is RunStatus.succeeded
    assert done.finished_at == "2026-09-09T03:00:00+00:00"
    again = refresh_run(done, store=store, queue=queue, now=_at("2026-09-09T04:00:00+00:00"))
    assert again.finished_at == "2026-09-09T03:00:00+00:00"


def test_refresh_run_blocked_step_means_attention(tmp_path: Path) -> None:
    store = _store(tmp_path)
    queue = RecordingQueue()
    run = start_run(
        _workflow(),
        store=store,
        queue=queue,
        now=_at("2026-09-09T02:00:00+00:00"),
        trigger=Trigger.manual,
    )
    queue.set_blocked(queue.creates[0]["id"], "need a human")
    refreshed = refresh_run(run, store=store, queue=queue, now=_at("2026-09-09T02:30:00+00:00"))
    assert refreshed.status is RunStatus.attention
    assert refreshed.finished_at == "2026-09-09T02:30:00+00:00"


def test_refresh_run_finished_run_skips_queue(tmp_path: Path) -> None:
    store = _store(tmp_path)
    queue = RecordingQueue()
    run = start_run(
        _workflow(),
        store=store,
        queue=queue,
        now=_at("2026-09-09T02:00:00+00:00"),
        trigger=Trigger.manual,
    )
    for item in queue.creates:
        queue.close(item["id"], "done")
    done = refresh_run(run, store=store, queue=queue, now=_at("2026-09-09T03:00:00+00:00"))
    listing: list = []

    class CountingQueue(RecordingQueue):
        def list_by_metadata(self, field: str, value: str) -> list[Task]:
            listing.append((field, value))
            return super().list_by_metadata(field, value)

    counting = CountingQueue()
    counting._tasks = queue._tasks
    counting._meta = queue._meta
    assert refresh_run(done, store=store, queue=counting, now=_at("2026-09-09T05:00:00+00:00"))
    assert listing == []


def _write_task_json(fleet_home: Path, task_id: str) -> None:
    """Minimal task.json so the kill path finds the running task's dir."""
    task_dir = fleet_home / "tasks" / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / "task.json").write_text("{}", encoding="utf-8")


def test_cancel_run_closes_waiting_kills_running(tmp_path: Path) -> None:
    store = _store(tmp_path)
    queue = RecordingQueue()
    run = start_run(
        _workflow(),
        store=store,
        queue=queue,
        now=_at("2026-09-09T02:00:00+00:00"),
        trigger=Trigger.manual,
    )
    running_id = queue.creates[0]["id"]
    queue.claim(running_id, "tester")
    _write_task_json(tmp_path, running_id)
    store.update_step_status(run.id, "lint", "in_progress", "2026-09-09T02:10:00+00:00")
    cancelled = cancel_run(
        run,
        store=store,
        queue=queue,
        now=_at("2026-09-09T03:00:00+00:00"),
        supervisor_running=True,
    )
    assert cancelled.status is RunStatus.cancelled
    assert cancelled.reason == "cancelled by operator"
    assert cancelled.finished_at == "2026-09-09T03:00:00+00:00"
    closed_ids = [task_id for task_id, _ in queue.closed]
    assert running_id not in closed_ids
    assert sorted(closed_ids) == sorted([queue.creates[1]["id"], queue.creates[2]["id"]])
    assert (tmp_path / "tasks" / running_id / ".kill").exists()


def test_cancel_run_custom_reason(tmp_path: Path) -> None:
    store = _store(tmp_path)
    run = start_run(
        _workflow(),
        store=store,
        queue=RecordingQueue(),
        now=_at("2026-09-09T02:00:00+00:00"),
        trigger=Trigger.manual,
    )
    cancelled = cancel_run(
        run,
        store=store,
        queue=FakeQueue(),
        now=_at("2026-09-09T03:00:00+00:00"),
        reason="superseded",
    )
    assert (cancelled.status, cancelled.reason) == (RunStatus.cancelled, "superseded")


def _inputs_workflow() -> Workflow:
    """One-stage workflow with a required, a defaulted, and a free input."""
    return Workflow(
        id="wf-inputs001",
        name="paper",
        description="d",
        defaults=Defaults(priority=2),
        inputs=(
            WorkflowInput(name="paper_url", description="URL.", required=True),
            WorkflowInput(name="focus", default="methods"),
            WorkflowInput(name="note", description="Free."),
        ),
        stages=(
            Stage(
                name="read",
                steps=(
                    Step(
                        name="fetch",
                        title="Fetch {{inputs.paper_url}}",
                        description="Focus on {{inputs.focus}} ({{inputs.note}}).",
                        isolation="none",
                    ),
                ),
            ),
        ),
    )


def test_resolve_inputs_fills_defaults() -> None:
    resolved = resolve_inputs(_inputs_workflow(), {"paper_url": "https://x.test"})
    assert resolved == {"paper_url": "https://x.test", "focus": "methods"}


def test_resolve_inputs_operator_value_wins() -> None:
    resolved = resolve_inputs(
        _inputs_workflow(), {"paper_url": "https://x.test", "focus": "results"}
    )
    assert resolved["focus"] == "results"


def test_resolve_inputs_unknown_name_raises() -> None:
    with pytest.raises(WorkflowInvalid, match="ghost"):
        resolve_inputs(_inputs_workflow(), {"paper_url": "https://x.test", "ghost": "1"})


def test_resolve_inputs_missing_required_raises() -> None:
    with pytest.raises(WorkflowInvalid, match="paper_url"):
        resolve_inputs(_inputs_workflow(), {"focus": "results"})


def test_start_run_stores_inputs_and_renders(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.save(_inputs_workflow())
    queue = RecordingQueue()
    run = start_run(
        _inputs_workflow(),
        store=store,
        queue=queue,
        now=_at("2026-09-09T02:00:00+00:00"),
        trigger=Trigger.manual,
        inputs={"paper_url": "https://x.test"},
    )
    assert run.inputs == {"paper_url": "https://x.test", "focus": "methods"}
    assert queue.creates[0]["title"] == "Fetch https://x.test"
    assert queue.creates[0]["description"] == "Focus on methods ({{inputs.note}})."
    assert _meta_of(queue.creates[0]["extra_args"])["fleet_isolation"] == "none"
    assert store.get_run(run.id) is not None
    assert store.get_run(run.id).inputs == run.inputs  # type: ignore[union-attr]


def test_start_run_missing_required_input_raises(tmp_path: Path) -> None:
    with pytest.raises(WorkflowInvalid, match="paper_url"):
        start_run(
            _inputs_workflow(),
            store=_store(tmp_path),
            queue=RecordingQueue(),
            now=_at("2026-09-09T02:00:00+00:00"),
            trigger=Trigger.manual,
            inputs={},
        )


def test_start_run_without_isolation_has_no_fleet_isolation(tmp_path: Path) -> None:
    queue = RecordingQueue()
    run = start_run(
        _workflow(),
        store=_store(tmp_path),
        queue=queue,
        now=_at("2026-09-09T02:00:00+00:00"),
        trigger=Trigger.manual,
    )
    assert "fleet_isolation" not in _meta_of(queue.creates[0]["extra_args"])
    assert run.inputs == {}

