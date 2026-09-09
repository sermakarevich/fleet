"""Tests for workers/base.py FnStep: stateless steps as data. Mirrors the source path."""

from __future__ import annotations

import asyncio
import dataclasses
import json
from pathlib import Path

import structlog

from fleet.core.config import RuntimeConfig
from fleet.core.task import Task, TaskOutcome
from fleet.state.paths import task_dir as _task_dir_path
from fleet.workers.base import (
    FnStep,
    StepContext,
    StepResult,
    StepStatus,
    Worker,
    WorkerRun,
    run_worker,
)


def _ctx(tmp_path: Path, task_id: str = "t-fn") -> StepContext:
    task = Task(id=task_id, title="t", description=None, status="in_progress")
    return StepContext(
        task=task,
        task_dir=_task_dir_path(tmp_path, task_id),
        workdir=tmp_path,
        fleet_home=tmp_path,
        coder=None,
        config=RuntimeConfig(),
        rate_gauge=None,  # type: ignore[arg-type]
        log=structlog.get_logger(),
    )


async def _ok(ctx: StepContext) -> StepResult:
    return StepResult(status=StepStatus.OK, reason=f"saw {ctx.task.id}")


def test_fn_step_runs_its_function(tmp_path: Path) -> None:
    """FnStep.run delegates to the wrapped function with the same ctx."""
    step = FnStep("probe", _ok)
    assert step.name == "probe"
    result = asyncio.run(step.run(_ctx(tmp_path)))
    assert result.status == StepStatus.OK
    assert result.reason == "saw t-fn"


def test_fn_step_records_name_in_run_json(tmp_path: Path) -> None:
    """run_worker records the FnStep name in run.json like any other step."""
    ctx = _ctx(tmp_path)
    asyncio.run(run_worker(Worker("w.fn", (FnStep("probe", _ok),)), ctx))
    data = json.loads((ctx.task_dir / "run.json").read_text(encoding="utf-8"))
    assert [s["name"] for s in data["steps"]] == ["probe"]


def test_fn_step_is_frozen(tmp_path: Path) -> None:
    """FnStep instances are immutable data: safe to share across attempts."""
    step = FnStep("probe", _ok)
    try:
        step.name = "other"  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        pass
    else:
        raise AssertionError("FnStep must be frozen")
    assert step.name == "probe"


def test_kill_on_step_without_cancel_is_noop(tmp_path: Path) -> None:
    """WorkerRun.kill skips steps that define no cancel instead of raising."""
    ctx = _ctx(tmp_path)
    gate = asyncio.Event()

    async def _hang(ctx: StepContext) -> StepResult:
        await gate.wait()
        return StepResult(status=StepStatus.OK)

    run = WorkerRun(Worker("w.fn", (FnStep("hang", _hang),)), ctx)

    async def _scenario():  # type: ignore[no-untyped-def]
        run_task = asyncio.create_task(run.run())
        await asyncio.sleep(0.05)
        await run.kill("manual_kill")  # must not raise: FnStep has no cancel
        await run.cancel()  # same for shutdown cancel
        gate.set()
        return await run_task

    outcome = asyncio.run(_scenario())
    assert outcome.outcome == TaskOutcome.SUCCESS
