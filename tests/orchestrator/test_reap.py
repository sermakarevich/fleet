"""Tests for orchestrator/reap.py::Reap. Mirrors the source path."""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path
from unittest.mock import MagicMock

from fleet.core.task import Task, TaskOutcome, TaskOutcomeRecord
from fleet.orchestrator.reap import Reap, outcome_of, pop_finished
from fleet.orchestrator.service import ServiceOrder
from fleet.orchestrator.state import SupervisorState
from tests.conftest import make_running_worker, make_supervisor


class StubQueue:
    """Minimal queue double: canned status, recorded writes."""

    def __init__(self, status: str = "in_progress") -> None:
        self._status = status
        self.released: list[tuple[str, str]] = []
        self.comments: list[tuple[str, str]] = []

    def get(self, task_id: str) -> Task:
        return Task(id=task_id, title="T", description=None, status=self._status)

    def release(self, task_id: str, reason: str = "", wait_sec: int = 0) -> None:
        self.released.append((task_id, reason))

    def comment(self, task_id: str, body: str) -> None:
        self.comments.append((task_id, body))

    def close(self, task_id: str, reason: str = "completed") -> None:
        pass

    def set_blocked(self, task_id: str, reason: str) -> None:
        pass


class _Recorder:
    """Service double that records on_worker_finished calls."""

    order = ServiceOrder.Logging
    name = "recorder"

    def __init__(self) -> None:
        self.finished: list[tuple] = []

    async def on_worker_finished(
        self, st: SupervisorState, worker, outcome: TaskOutcomeRecord
    ) -> None:
        self.finished.append((worker, outcome))


def test_pop_finished_removes_worker(tmp_path: Path) -> None:
    """pop_finished takes the matching worker out of state.running."""
    sup = make_supervisor(tmp_path, services=[], checks=[])
    fut: asyncio.Task = MagicMock()
    worker = make_running_worker("t-001", tmp_path, future=fut)
    sup.state.running["t-001"] = worker

    assert pop_finished(sup.state, fut) is worker
    assert sup.state.running == {}
    assert pop_finished(sup.state, fut) is None


def test_outcome_of_failure_on_raised_future() -> None:
    """A future that raised becomes a FAILURE naming the exception."""

    async def _run() -> TaskOutcomeRecord:
        async def _boom() -> TaskOutcomeRecord:
            raise RuntimeError("kablam")

        fut = asyncio.ensure_future(_boom())
        with contextlib.suppress(RuntimeError):
            await fut
        return outcome_of(fut)

    record = asyncio.run(_run())
    assert record.outcome is TaskOutcome.FAILURE
    assert "kablam" in record.reason


def test_reap_emits_on_worker_finished(tmp_path: Path) -> None:
    """A finished future is reaped and emitted with the same worker and outcome."""
    queue = StubQueue(status="in_progress")
    recorder = _Recorder()
    sup = make_supervisor(tmp_path, queue=queue, services=[recorder], checks=[])  # type: ignore[arg-type]

    async def _run() -> None:
        expected = TaskOutcomeRecord(outcome=TaskOutcome.SUCCESS, exit_code=0, reason="")

        async def _ok() -> TaskOutcomeRecord:
            return expected

        fut = asyncio.create_task(_ok())
        await fut  # finish before serve starts; wait() still reports it done
        worker = make_running_worker(
            "t-001",
            tmp_path,
            task=Task(id="t-001", title="T", description=None, status="in_progress"),
            run=MagicMock(),
            future=fut,
        )
        sup.state.running["t-001"] = worker

        serve_task = asyncio.create_task(Reap().serve(sup.state))
        for _ in range(200):
            if recorder.finished:
                break
            await asyncio.sleep(0.01)
        sup.state.shutting_down = True
        await asyncio.wait_for(serve_task, timeout=2.0)

    asyncio.run(_run())

    assert len(recorder.finished) == 1
    worker, outcome = recorder.finished[0]
    assert worker.task.id == "t-001"
    assert outcome.outcome is TaskOutcome.SUCCESS
    assert outcome.exit_code == 0
    assert sup.state.running == {}
