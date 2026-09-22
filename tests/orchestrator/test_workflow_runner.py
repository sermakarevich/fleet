"""WorkflowRunner (ADR 0015 §2): the one WorkflowRunnerLike implementation.

Uses the fake builder workflow (tests/workflows/fake_builder.py, one stage
"s1" with steps a/b) so start() exercises the real run engine end to end
against a throwaway WorkflowStore and FakeQueue.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest

from fleet.orchestrator.workflow_runner import WorkflowRunner
from fleet.workflows import builders
from fleet.workflows.model import Workflow, WorkflowInput
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
