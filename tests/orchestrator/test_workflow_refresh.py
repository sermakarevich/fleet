"""Tests for orchestrator/workflow_refresh.py: the tick that folds bead statuses in."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import structlog

from fleet.core.clock import FakeClock
from fleet.core.limits import WORKFLOW_REFRESH_SEC
from fleet.core.task import Task
from fleet.orchestrator.service import ServiceOrder
from fleet.orchestrator.workflow_refresh import (
    make_workflow_refresh,
    workflow_refresh_pass,
    workflow_refresh_tick,
)
from fleet.workflows.model import Defaults, RunStatus, Stage, Step, Workflow
from fleet.workflows.model import Trigger as WorkflowTrigger
from fleet.workflows.runs import start_run
from fleet.workflows.store import WorkflowStore
from tests.conftest import FakeQueue, make_supervisor

NOW = datetime(2026, 9, 9, 0, 5, tzinfo=UTC)


def _workflow() -> Workflow:
    """Two parallel steps, so one tick folds two tasks into the run."""
    return Workflow(
        id="wf-test0001",
        name="nightly",
        description="d",
        defaults=Defaults(priority=2),
        stages=(
            Stage(
                name="checks",
                steps=(
                    Step(name="lint", title="Lint"),
                    Step(name="tests", title="Run tests"),
                ),
            ),
        ),
    )


def _store(tmp_path: Path) -> WorkflowStore:
    """Throwaway store with the demo workflow saved."""
    store = WorkflowStore(tmp_path / "workflows.db")
    store.save(
        replace(
            _workflow(),
            created_at="2026-09-09T00:00:00+00:00",
            updated_at="2026-09-09T00:00:00+00:00",
        )
    )
    return store


class CountingQueue(FakeQueue):
    """FakeQueue that counts bead-listing calls (the bd calls a tick may skip)."""

    def __init__(self, tasks: list[Task] | None = None) -> None:
        super().__init__(tasks)
        self.list_calls = 0

    def list_by_metadata(self, field: str, value: str) -> list[Task]:
        """Count the call, then answer from the in-memory tasks."""
        self.list_calls += 1
        return super().list_by_metadata(field, value)


def _state(tmp_path: Path, queue: FakeQueue):
    """Supervisor state over tmp_path with a FakeClock at NOW."""
    sup = make_supervisor(tmp_path, queue=queue, services=[], checks=[])
    st = sup.state
    st.clock = FakeClock(start=NOW)
    return st


def test_factory_defaults() -> None:
    """Default cadence is WORKFLOW_REFRESH_SEC with the WorkflowRefresh order."""
    svc = make_workflow_refresh()
    assert svc.name == "workflow_refresh"
    assert svc.order == ServiceOrder.WorkflowRefresh
    assert svc.interval_sec == WORKFLOW_REFRESH_SEC
    assert svc.tick is workflow_refresh_tick
    assert ServiceOrder.Reap < ServiceOrder.WorkflowRefresh < ServiceOrder.Stall


def test_tick_finishes_run_when_all_tasks_closed(tmp_path: Path) -> None:
    """A running run whose beads all closed becomes succeeded with finished_at."""
    store = _store(tmp_path)
    queue = CountingQueue()
    run = start_run(
        _workflow(),
        store=store,
        queue=queue,
        now=NOW,
        trigger=WorkflowTrigger.manual,
    )
    for task in list(queue._tasks.values()):
        queue.close(task.id, "done")

    st = _state(tmp_path, queue)
    asyncio.run(workflow_refresh_tick(st))

    finished = store.get_run(run.id)
    assert finished is not None
    assert finished.status is RunStatus.succeeded
    assert finished.finished_at == NOW.isoformat()
    assert queue.list_calls >= 1


def test_tick_leaves_finished_runs_alone(tmp_path: Path) -> None:
    """Nothing open means no bead listing call at all."""
    store = _store(tmp_path)
    queue = CountingQueue()
    run = start_run(
        _workflow(),
        store=store,
        queue=queue,
        now=NOW,
        trigger=WorkflowTrigger.manual,
    )
    for task in list(queue._tasks.values()):
        queue.close(task.id, "done")
    assert workflow_refresh_pass(tmp_path, queue, NOW, structlog.get_logger()) == 1

    fresh = CountingQueue()
    st = _state(tmp_path, fresh)
    asyncio.run(workflow_refresh_tick(st))

    assert fresh.list_calls == 0
    assert store.get_run(run.id) is not None
    assert store.get_run(run.id).status is RunStatus.succeeded
