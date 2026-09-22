"""Cancel tests: cancelling a run closes every live step bead.

Covers `runs.cancel_run` (shared by the API handler and the CLI): blocked and
deferred beads close with the run-cancelled reason, stored rows sync to
closed, one failing close never orphans the rest, and cancelling twice is a
no-op. Runs on `FakeQueue` plus a throwaway `WorkflowStore`; no test ever
touches the real `bd` binary.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from pathlib import Path

from fleet.beads.client import BdError
from fleet.core.task import Task
from fleet.workflows.model import Defaults, RunStatus, Stage, Step, Trigger, Workflow
from fleet.workflows.runs import cancel_run, start_run
from fleet.workflows.store import WorkflowStore
from tests.conftest import FakeQueue


def _at(raw: str) -> datetime:
    """Parse one test timestamp as aware UTC."""
    return datetime.fromisoformat(raw)


def _workflow() -> Workflow:
    """Two first-stage steps plus a summary that quotes both task ids."""
    return Workflow(
        id="wf-cancel0001",
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
        self.creates.append({"id": task.id, "extra_args": extra_args or ""})
        return task


def test_cancel_run_closes_blocked_and_deferred_leaves_zero_live(tmp_path: Path) -> None:
    """Blocked + deferred steps both close; stored rows sync; repeat is a no-op."""
    store = _store(tmp_path)
    queue = RecordingQueue()
    run = start_run(
        _workflow(),
        store=store,
        queue=queue,
        now=_at("2026-09-09T02:00:00+00:00"),
        trigger=Trigger.manual,
    )
    ids = [item["id"] for item in queue.creates]
    assert len(ids) == 3
    queue._tasks[ids[0]] = replace(queue._tasks[ids[0]], status="blocked")
    queue._tasks[ids[2]] = replace(queue._tasks[ids[2]], status="deferred")
    # Stale stored row: the db thinks the deferred step already closed.
    store.update_step_status(run.id, "summary", "closed", "2026-09-09T02:30:00+00:00")
    cancelled = cancel_run(
        run,
        store=store,
        queue=queue,
        now=_at("2026-09-09T03:00:00+00:00"),
        supervisor_running=False,
    )
    assert cancelled.status is RunStatus.cancelled
    assert cancelled.reason == "cancelled by operator"
    live = [
        task
        for task in queue.list_by_metadata("fleet_workflow_run", run.id)
        if task.status != "closed"
    ]
    assert live == []
    assert {step.task_status for step in store.step_runs(run.id)} == {"closed"}
    assert {reason for _, reason in queue.closed} == {f"workflow run {run.id} cancelled"}
    again = cancel_run(
        store.get_run(run.id),  # type: ignore[arg-type]
        store=store,
        queue=queue,
        now=_at("2026-09-09T04:00:00+00:00"),
        supervisor_running=False,
    )
    assert again.status is RunStatus.cancelled
    remaining = queue.list_by_metadata("fleet_workflow_run", run.id)
    assert remaining and all(task.status == "closed" for task in remaining)


def test_cancel_run_close_failure_never_orphans_rest(tmp_path: Path) -> None:
    """One bead that refuses to close is logged; the rest still close."""

    class FlakyQueue(RecordingQueue):
        def close(self, task_id: str, reason: str = "completed") -> None:
            if task_id == self.creates[0]["id"]:
                raise BdError("boom")
            super().close(task_id, reason)

    store = _store(tmp_path)
    queue = FlakyQueue()
    run = start_run(
        _workflow(),
        store=store,
        queue=queue,
        now=_at("2026-09-09T02:00:00+00:00"),
        trigger=Trigger.manual,
    )
    cancelled = cancel_run(
        run,
        store=store,
        queue=queue,
        now=_at("2026-09-09T03:00:00+00:00"),
        supervisor_running=False,
    )
    assert cancelled.status is RunStatus.cancelled
    assert queue._tasks[queue.creates[1]["id"]].status == "closed"
    assert queue._tasks[queue.creates[2]["id"]].status == "closed"
