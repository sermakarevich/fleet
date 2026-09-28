"""Tests for orchestrator/flow_coder.py: synthetic tasks, worker launch, outcome fold."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

from fleet.core.task import Task
from fleet.flows.folders import Catalog
from fleet.flows.model import Flow, Step
from fleet.orchestrator import flow_coder as flow_coder_mod
from fleet.orchestrator.flow_coder import (
    coder_outcome,
    start_coder_step,
    step_task,
    step_task_id,
)
from fleet.orchestrator.flow_service import FlowState, settle
from fleet.runs import engine
from fleet.runs.run_dir import NO_ITEM, outputs_file
from fleet.runs.store import RunStatus, RunStore, StepStatus
from fleet.workers.base import FnStep, StepResult, Worker
from fleet.workers.base import StepStatus as WorkerStepStatus
from tests.conftest import FakeQueue, make_supervisor

NOW = datetime(2026, 9, 28, 7, 0, 0, tzinfo=UTC)


class StubCoder:
    """Coder double: resolve_coder reads .spec/.name/.model off it."""

    name = "stub"
    model = "stub-model"


def _flow_source(tmp_path: Path) -> Path:
    source = tmp_path / "demo.yaml"
    source.write_text("fleet_flow: 2\n", encoding="utf-8")
    return source


def _launch(tmp_path: Path, **step_kw):
    """One real coder Launch via start_run + advance (attempt 1, row running)."""
    fleet_home = tmp_path / "fleet-home"
    step = Step(name="draft", prompt="Write it", **step_kw)
    flow = Flow(name="demo", steps=(step,), source=str(_flow_source(tmp_path)))
    store = RunStore(fleet_home / "runs.db")
    run = engine.start_run(store, fleet_home, flow, {}, NOW)
    adv = engine.advance(
        store,
        flow,
        run,
        fleet_home / "runs" / run.id,
        NOW,
        defaults={"coder": "stub", "model": "m", "isolation": "none", "retries": 0},
    )
    (launch,) = adv.launches
    return store, run, flow, launch


def _state(tmp_path: Path):
    sup = make_supervisor(
        tmp_path,
        queue=FakeQueue(),
        coder=StubCoder(),  # type: ignore[arg-type]
        services=[],
        checks=[],
    )
    return sup.state


def _install_fake_worker(monkeypatch, seen: dict, *, status: str = "done") -> None:
    """select_worker double: records prompt.md, publishes outputs + RESULT."""

    async def _fake(ctx) -> StepResult:
        seen[ctx.attempt_n] = (ctx.attempt_dir / "prompt.md").read_text(encoding="utf-8")
        (ctx.task_dir / "outputs.json").write_text(json.dumps({"n": 1}), encoding="utf-8")
        (ctx.task_dir / "RESULT.json").write_text(
            json.dumps({"schema": 1, "status": status, "summary": "did it"}),
            encoding="utf-8",
        )
        return StepResult(status=WorkerStepStatus.OK, reason="")

    def _select(task: Task, ctx, queue=None) -> Worker:
        return Worker(name="fake", steps=(FnStep(name="fake", fn=_fake),))

    monkeypatch.setattr(flow_coder_mod, "select_worker", _select)


def test_step_task_fields(tmp_path: Path) -> None:
    """The synthetic task names, titles, and routes off the launch + run."""
    _, run, _, launch = _launch(tmp_path)
    task = step_task(launch, run)
    assert task.id == f"{run.id}.draft"
    assert step_task_id(launch, run) == task.id
    assert task.title == "demo/draft"
    assert task.description == launch.prompt == "Write it"
    assert task.status == "in_progress"
    assert task.cwd == str(launch.cwd)
    assert task.coder == "stub"
    assert task.isolation == "none"
    assert task.worker is None


def test_start_coder_step_runs_worker(tmp_path: Path, monkeypatch) -> None:
    """The fake coder factory yields a FlowWorker whose future completes."""
    store, run, _, launch = _launch(tmp_path)
    st = _state(tmp_path)
    seen: dict = {}
    _install_fake_worker(monkeypatch, seen)

    async def _run():
        worker = start_coder_step(st, launch, run)
        assert worker.task.id == f"{run.id}.draft"
        assert worker.run_id == run.id
        assert worker.attempt_dir == launch.step_dir / "attempts" / "1"
        assert (worker.attempt_dir / "prompt.md").read_text(encoding="utf-8") == "Write it"
        assert st.running == {}
        record = await worker.future
        assert record.outcome.name == "SUCCESS"
        return worker

    worker = asyncio.run(_run())
    assert seen[1] == "Write it"
    assert worker.future.done()
    _ = store


def test_start_coder_step_feedback_in_prompt(tmp_path: Path, monkeypatch) -> None:
    """Retry feedback appends a trailing section to prompt.md."""
    _, run, _, launch = _launch(tmp_path)
    st = _state(tmp_path)
    seen: dict = {}
    _install_fake_worker(monkeypatch, seen)

    async def _run():
        worker = start_coder_step(st, launch, run, "# Previous attempt failed check `x`\n\nbad\n")
        await worker.future

    asyncio.run(_run())
    assert seen[1] == "Write it\n\n# Previous attempt failed check `x`\n\nbad\n"


def test_coder_outcome_copies_outputs(tmp_path: Path, monkeypatch) -> None:
    """A done worker folds to ok and its bare outputs.json lands nested."""
    _, run, _, launch = _launch(tmp_path)
    st = _state(tmp_path)
    seen: dict = {}
    _install_fake_worker(monkeypatch, seen)

    async def _run():
        worker = start_coder_step(st, launch, run)
        await worker.future
        return worker

    worker = asyncio.run(_run())
    ok, reason = coder_outcome(worker)
    assert (ok, reason) == (True, "did it")
    assert json.loads(outputs_file(launch.step_dir).read_text(encoding="utf-8")) == {"n": 1}


def test_coder_outcome_failure(tmp_path: Path, monkeypatch) -> None:
    """A failed worker step is not ok and names the step."""
    _, run, _, launch = _launch(tmp_path)
    st = _state(tmp_path)

    async def _boom(ctx) -> StepResult:
        return StepResult(status=WorkerStepStatus.FAIL, reason="kablam")

    def _select(task: Task, ctx, queue=None) -> Worker:
        return Worker(name="fake", steps=(FnStep(name="fake", fn=_boom),))

    monkeypatch.setattr(flow_coder_mod, "select_worker", _select)

    async def _run():
        worker = start_coder_step(st, launch, run)
        await worker.future
        return worker

    worker = asyncio.run(_run())
    ok, reason = coder_outcome(worker)
    assert not ok
    assert "kablam" in reason


def test_coder_outcome_partial_folds(tmp_path: Path, monkeypatch) -> None:
    """RESULT partial folds the SUCCESS exit into not-ok."""
    _, run, _, launch = _launch(tmp_path)
    st = _state(tmp_path)
    seen: dict = {}
    _install_fake_worker(monkeypatch, seen, status="partial")

    async def _run():
        worker = start_coder_step(st, launch, run)
        await worker.future
        return worker

    worker = asyncio.run(_run())
    ok, _ = coder_outcome(worker)
    assert not ok


def test_settle_marks_succeeded(tmp_path: Path, monkeypatch) -> None:
    """Settling an ok coder launch with no checks marks the row succeeded."""
    store, run, flow, launch = _launch(tmp_path)
    st = _state(tmp_path)
    seen: dict = {}
    _install_fake_worker(monkeypatch, seen)
    fs = FlowState(
        catalog=Catalog(flows={"demo": flow}, tools={}, problems=[]),
        store=store,
        coders={},
        tools={},
        humans={},
    )

    async def _run():
        worker = start_coder_step(st, launch, run)
        await worker.future
        ok, reason = coder_outcome(worker)
        await settle(st, fs, launch, run.id, ok, reason)

    asyncio.run(_run())
    row = store.get_step_run(run.id, "draft", NO_ITEM)
    assert row is not None and row.status is StepStatus.succeeded
    assert store.get_run(run.id) is not None
    assert store.get_run(run.id).status is RunStatus.running
