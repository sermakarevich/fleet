"""WorkflowRunner (ADR 0015 §2): the one WorkflowRunnerLike implementation.

Uses the fake builder workflow (tests/workflows/fake_builder.py, one stage
"s1" with steps a/b) so start() exercises the real run engine end to end
against a throwaway WorkflowStore and FakeQueue.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest
import structlog

from fleet.core.config import RuntimeConfig
from fleet.core.task import Task
from fleet.orchestrator.workflow_runner import WorkflowRunner
from fleet.state import paths as state_paths
from fleet.workers.base import StepContext, StepStatus
from fleet.workers.job import SpawnChildren
from fleet.workflows import builders
from fleet.workflows.model import RunStatus, Stage, Step, Trigger, Workflow, WorkflowInput
from fleet.workflows.store import WorkflowStore
from tests.conftest import FakeQueue

_STAMP = "2026-09-09T00:00:00+00:00"


def _register_fake(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(builders.BUILDER_MODULES, "fake", "tests.workflows.fake_builder")


def _builder_workflow(name: str = "builder-demo") -> Workflow:
    return Workflow(
        id="wf-builder001",
        name=name,
        description="d",
        inputs=(WorkflowInput(name="url"),),
        stages=(),
        builder="fake",
    )


def _store_with(workflow: Workflow, tmp_path: Path) -> WorkflowStore:
    store = WorkflowStore(tmp_path / "workflows.db")
    store.save(replace(workflow, created_at=_STAMP, updated_at=_STAMP))
    return store


def _now() -> datetime:
    return datetime.fromisoformat("2026-09-09T02:00:00+00:00")


def test_start_returns_last_stage_as_final_task_ids(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _register_fake(monkeypatch)
    workflow = _builder_workflow()
    store = _store_with(workflow, tmp_path)
    queue = FakeQueue()
    runner = WorkflowRunner(store, queue, _now)

    handle = runner.start(workflow.id, {"url": "https://example.com"})

    run = store.get_run(handle.run_id)
    assert run is not None
    steps = store.step_runs(run.id)
    last_stage = len(run.spec.stages) - 1
    expected_final = {s.task_id for s in steps if s.stage_index == last_stage}
    assert set(handle.final_task_ids) == expected_final
    assert set(handle.task_ids) == {s.task_id for s in steps}
    assert handle.final_task_ids  # the fake builder's only stage is the last one


def test_start_resolves_by_name(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _register_fake(monkeypatch)
    workflow = _builder_workflow(name="by-name")
    store = _store_with(workflow, tmp_path)
    runner = WorkflowRunner(store, FakeQueue(), _now)

    handle = runner.start("by-name", {"url": "https://example.com"})

    assert store.get_run(handle.run_id) is not None


def test_start_unknown_ref_raises(tmp_path: Path) -> None:
    store = WorkflowStore(tmp_path / "workflows.db")
    runner = WorkflowRunner(store, FakeQueue(), _now)

    with pytest.raises(ValueError, match="not found"):
        runner.start("wf-missing1", {})

    with pytest.raises(ValueError, match="not found"):
        runner.start("missing-name", {})


def test_start_reuses_run_with_identical_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Starting twice with the same inputs yields one run, no new beads."""
    _register_fake(monkeypatch)
    workflow = _builder_workflow()
    store = _store_with(workflow, tmp_path)
    queue = FakeQueue()
    runner = WorkflowRunner(store, queue, _now)

    first = runner.start(workflow.id, {"url": "https://example.com"})
    created_before = len(queue.created)

    second = runner.start(workflow.id, {"url": "https://example.com"})

    assert second.run_id == first.run_id
    assert second.task_ids == first.task_ids
    assert second.final_task_ids == first.final_task_ids
    assert store.run_count(workflow.id) == 1
    assert len(queue.created) == created_before


def test_start_starts_fresh_for_different_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _register_fake(monkeypatch)
    workflow = _builder_workflow()
    store = _store_with(workflow, tmp_path)
    runner = WorkflowRunner(store, FakeQueue(), _now)

    first = runner.start(workflow.id, {"url": "https://a.test"})
    second = runner.start(workflow.id, {"url": "https://b.test"})

    assert second.run_id != first.run_id
    assert store.run_count(workflow.id) == 2


def test_start_ignores_cancelled_and_failed_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A run the operator killed (or that died) must not shadow a fresh start."""
    _register_fake(monkeypatch)
    workflow = _builder_workflow()
    store = _store_with(workflow, tmp_path)
    runner = WorkflowRunner(store, FakeQueue(), _now)

    first = runner.start(workflow.id, {"url": "https://example.com"})
    store.finish_run(first.run_id, RunStatus.cancelled, "operator", _STAMP)
    second = runner.start(workflow.id, {"url": "https://example.com"})
    assert second.run_id != first.run_id

    store.finish_run(second.run_id, RunStatus.failed, "doomed", _STAMP)
    third = runner.start(workflow.id, {"url": "https://example.com"})
    assert third.run_id != second.run_id
    assert store.run_count(workflow.id) == 3


def test_start_reuses_succeeded_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _register_fake(monkeypatch)
    workflow = _builder_workflow()
    store = _store_with(workflow, tmp_path)
    runner = WorkflowRunner(store, FakeQueue(), _now)

    first = runner.start(workflow.id, {"url": "https://example.com"})
    store.finish_run(first.run_id, RunStatus.succeeded, "", _STAMP)

    assert runner.start(workflow.id, {"url": "https://example.com"}).run_id == first.run_id
    assert store.run_count(workflow.id) == 1


def test_spawn_retry_after_kill_creates_no_second_chain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A killed spawn (intent journaled, run orphaned) retries onto the same run.

    End to end through SpawnChildren with the real WorkflowRunner: attempt 1
    created the run but died before journaling the completion, leaving only
    the ``starting`` breadcrumb; attempt 2 must claim the orphan via the
    inputs dedupe instead of starting a second chain.
    """
    _register_fake(monkeypatch)
    workflow = _builder_workflow()
    store = _store_with(workflow, tmp_path)
    beads = FakeQueue()
    runner = WorkflowRunner(store, beads, _now)

    inputs = {"url": "https://example.com/orphan"}
    orphan = runner.start(workflow.id, inputs)

    task_dir = state_paths.task_dir(tmp_path, "job-1")
    task_dir.mkdir(parents=True, exist_ok=True)
    artifacts = task_dir / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    (artifacts / "tasks.json").write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "key": "src-01",
                        "title": "orphan source",
                        "workflow": workflow.id,
                        "inputs": dict(inputs),
                    }
                ]
            }
        )
    )
    (artifacts / "children_runs.json").write_text(
        json.dumps(
            {"src-01": {"status": "starting", "workflow": workflow.id, "inputs": dict(inputs)}}
        )
    )
    ctx = StepContext(
        task=Task(id="job-1", title="job", description="goal", status="in_progress"),
        task_dir=task_dir,
        workdir=tmp_path,
        fleet_home=tmp_path,
        coder=None,
        config=RuntimeConfig(),
        rate_gauge=None,  # type: ignore[arg-type]
        log=structlog.get_logger(),
        attempt_dir=task_dir / "attempts" / "2",
        attempt_n=2,
        workflow_runner=runner,
    )
    result = asyncio.run(SpawnChildren(beads).run(ctx))

    assert result.status == StepStatus.OK
    assert store.run_count(workflow.id) == 1, "retry must not start a second chain"
    journaled = json.loads((artifacts / "children_runs.json").read_text())
    assert journaled["src-01"]["run_id"] == orphan.run_id


def _plain_workflow() -> Workflow:
    """A one-step workflow needing no builder (plain start path)."""
    return Workflow(
        id="wf-plain0001",
        name="plain",
        description="d",
        stages=(Stage(name="only", steps=(Step(name="do", title="Do it"),)),),
    )


def test_start_without_parent_is_manual(tmp_path: Path) -> None:
    """A plain start records no parent and keeps the manual trigger."""
    store = _store_with(_plain_workflow(), tmp_path)
    runner = WorkflowRunner(store, FakeQueue(), _now)

    handle = runner.start("wf-plain0001", {})

    run = store.get_run(handle.run_id)
    assert run is not None
    assert run.trigger is Trigger.manual
    assert run.parent_run_id is None and run.parent_task_id is None


def test_start_with_parent_task_resolves_parent_run(tmp_path: Path) -> None:
    """A job's own task id resolves the run owning that step as the parent."""
    store = _store_with(_plain_workflow(), tmp_path)
    runner = WorkflowRunner(store, FakeQueue(), _now)

    first = runner.start("wf-plain0001", {})
    epic_task = store.step_runs(first.run_id)[0].task_id
    store.finish_run(first.run_id, RunStatus.cancelled, "operator", _STAMP)

    second = runner.start("wf-plain0001", {}, parent_task_id=epic_task)

    run = store.get_run(second.run_id)
    assert run is not None and run.id != first.run_id
    assert run.trigger is Trigger.parent
    assert run.parent_run_id == first.run_id
    assert run.parent_task_id == epic_task


def test_start_with_unknown_parent_task_keeps_task_id(tmp_path: Path) -> None:
    """A parent task owning no step still marks the trigger honestly."""
    store = _store_with(_plain_workflow(), tmp_path)
    runner = WorkflowRunner(store, FakeQueue(), _now)

    handle = runner.start("wf-plain0001", {}, parent_task_id="fleet-epic1")

    run = store.get_run(handle.run_id)
    assert run is not None
    assert run.trigger is Trigger.parent
    assert run.parent_run_id is None
    assert run.parent_task_id == "fleet-epic1"


def test_spawn_records_parent_task_on_child_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End to end: a job-spawned run names the epic task that spawned it."""
    _register_fake(monkeypatch)
    workflow = _builder_workflow()
    store = _store_with(workflow, tmp_path)
    beads = FakeQueue()
    runner = WorkflowRunner(store, beads, _now)

    task_dir = state_paths.task_dir(tmp_path, "job-1")
    artifacts = task_dir / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    (artifacts / "tasks.json").write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "key": "src-01",
                        "title": "spawned source",
                        "workflow": workflow.id,
                        "inputs": {"url": "https://example.com/child"},
                    }
                ]
            }
        )
    )
    ctx = StepContext(
        task=Task(id="job-1", title="job", description="goal", status="in_progress"),
        task_dir=task_dir,
        workdir=tmp_path,
        fleet_home=tmp_path,
        coder=None,
        config=RuntimeConfig(),
        rate_gauge=None,  # type: ignore[arg-type]
        log=structlog.get_logger(),
        attempt_dir=task_dir / "attempts" / "1",
        attempt_n=1,
        workflow_runner=runner,
    )
    result = asyncio.run(SpawnChildren(beads).run(ctx))

    assert result.status == StepStatus.OK
    journaled = json.loads((artifacts / "children_runs.json").read_text())
    child = store.get_run(journaled["src-01"]["run_id"])
    assert child is not None
    assert child.trigger is Trigger.parent
    assert child.parent_task_id == "job-1"
    assert child.parent_run_id is None  # the epic is no workflow step
