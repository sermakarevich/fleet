"""Tests for the worker step pipeline (unit under test: workers/base.py)."""

import asyncio
import json
from pathlib import Path

import structlog

from fleet.core.config import RuntimeConfig
from fleet.core.task import Task, TaskOutcome, TaskOutcomeRecord
from fleet.state.paths import task_dir
from fleet.workers.base import StepContext, StepResult, StepStatus, Worker, WorkerRun, run_worker
from tests.helpers.wait import await_until


class _RecordingStep:
    """A step that records calls, returns a fixed StepResult, and can hang."""

    def __init__(
        self, name: str, status: StepStatus = StepStatus.OK, reason: str = "", hang: bool = False
    ):
        self.name = name
        self._status = status
        self._reason = reason
        self._hang = hang
        self.ran = False
        self.cancel_reason: str | None = None
        self._cancel_event = asyncio.Event() if hang else None

    async def run(self, ctx: StepContext) -> StepResult:
        self.ran = True
        if self._hang:
            assert self._cancel_event is not None
            await self._cancel_event.wait()
            return StepResult(
                status=StepStatus.OUTCOME,
                outcome=TaskOutcomeRecord(
                    outcome=TaskOutcome.KILLED, reason=self.cancel_reason or ""
                ),
            )
        outcome = None
        if self._status == StepStatus.OUTCOME:
            outcome = TaskOutcomeRecord(outcome=TaskOutcome.SUCCESS, exit_code=0)
        return StepResult(status=self._status, reason=self._reason, outcome=outcome)

    async def cancel(self, reason: str) -> None:
        self.cancel_reason = reason
        if self._cancel_event is not None:
            self._cancel_event.set()


class _RaisingStep:
    name = "boom"

    async def run(self, ctx: StepContext) -> StepResult:
        raise RuntimeError("kaboom")

    async def cancel(self, reason: str) -> None:
        return None


def _ctx(tmp_path: Path, task_id: str = "t-001") -> StepContext:
    task = Task(id=task_id, title="t", description=None, status="in_progress")
    return StepContext(
        task=task,
        task_dir=task_dir(tmp_path, task_id),
        workdir=tmp_path,
        fleet_home=tmp_path,
        coder=None,
        config=RuntimeConfig(),
        rate_gauge=None,  # type: ignore[arg-type]
        log=structlog.get_logger(),
    )


def _run_json(ctx: StepContext) -> dict:
    return json.loads((ctx.task_dir / "run.json").read_text(encoding="utf-8"))


def test_all_ok_steps_run_in_order_and_return_success(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    a, b = _RecordingStep("a"), _RecordingStep("b")
    worker = Worker("w.test", (a, b))

    outcome = asyncio.run(run_worker(worker, ctx))

    assert a.ran and b.ran
    assert outcome.outcome == TaskOutcome.SUCCESS
    assert outcome.exit_code == 0


def test_stops_at_first_fail(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    a = _RecordingStep("a", status=StepStatus.FAIL, reason="bad input")
    b = _RecordingStep("b")
    worker = Worker("w.test", (a, b))

    outcome = asyncio.run(run_worker(worker, ctx))

    assert a.ran and not b.ran
    assert outcome.outcome == TaskOutcome.FAILURE
    assert "a" in outcome.reason
    assert "bad input" in outcome.reason


def test_stops_at_first_outcome(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    a = _RecordingStep("a", status=StepStatus.OUTCOME)
    b = _RecordingStep("b")
    worker = Worker("w.test", (a, b))

    outcome = asyncio.run(run_worker(worker, ctx))

    assert a.ran and not b.ran
    assert outcome.outcome == TaskOutcome.SUCCESS


def test_unexpected_exception_becomes_failure(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    worker = Worker("w.test", (_RaisingStep(),))

    outcome = asyncio.run(run_worker(worker, ctx))

    assert outcome.outcome == TaskOutcome.FAILURE
    assert "unexpected exception" in outcome.reason
    assert "kaboom" in outcome.reason


def test_steps_recorded_in_run_json(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    a, b = _RecordingStep("a"), _RecordingStep("b", status=StepStatus.OUTCOME)
    worker = Worker("w.test", (a, b))

    asyncio.run(run_worker(worker, ctx))

    data = _run_json(ctx)
    assert data["worker"] == "w.test"
    names = [s["name"] for s in data["steps"]]
    assert names == ["a", "b"]
    for entry in data["steps"]:
        assert entry["started_at"] and entry["ended_at"]


def test_failed_step_still_recorded_in_run_json(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    worker = Worker("w.test", (_RaisingStep(),))

    asyncio.run(run_worker(worker, ctx))

    data = _run_json(ctx)
    assert data["steps"][0]["name"] == "boom"
    assert data["steps"][0]["status"] == "fail"


def test_kill_forwards_to_current_step(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    hanging = _RecordingStep("hanging", hang=True)
    never = _RecordingStep("never")
    worker = Worker("w.test", (hanging, never))
    run = WorkerRun(worker, ctx)

    async def _scenario() -> None:
        run_task = asyncio.create_task(run.run())
        assert await await_until(lambda: hanging.ran), "step never started"
        await run.kill("manual_kill")
        await run_task

    asyncio.run(_scenario())

    assert hanging.cancel_reason == "manual_kill"
    assert not never.ran


def test_cancel_forwards_supervisor_shutdown_to_current_step(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    hanging = _RecordingStep("hanging", hang=True)
    worker = Worker("w.test", (hanging,))
    run = WorkerRun(worker, ctx)

    async def _scenario() -> None:
        run_task = asyncio.create_task(run.run())
        assert await await_until(lambda: hanging.ran), "step never started"
        await run.cancel()
        await run_task

    asyncio.run(_scenario())

    assert hanging.cancel_reason == "supervisor_shutdown"
