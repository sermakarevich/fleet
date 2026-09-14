"""Builder expansion tests: validation, YAML round trip, start_run, show."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest
import yaml

from fleet.cli.render import print_workflow_show
from fleet.core.errors import WorkflowInvalid
from fleet.workflows import builders
from fleet.workflows.builders.sources import SourceError
from fleet.workflows.model import Trigger, Workflow, WorkflowInput, ensure_valid, validate
from fleet.workflows.runs import start_run
from fleet.workflows.store import WorkflowStore
from fleet.workflows.yaml_io import from_yaml, to_yaml
from tests.conftest import FakeQueue
from tests.workflows import fake_builder
from tests.workflows.test_runs import RecordingQueue
from tests.workflows.test_runs import _workflow as _plain_workflow

_STAMP = "2026-09-09T00:00:00+00:00"
_AT = "2026-09-09T02:00:00+00:00"


def _register_fake(monkeypatch: pytest.MonkeyPatch) -> None:
    """Point the 'fake' builder name at the test-only fake module."""
    monkeypatch.setitem(builders.BUILDER_MODULES, "fake", "tests.workflows.fake_builder")


def _builder_workflow() -> Workflow:
    """Builder workflow with no stages and one input used by the fake title."""
    return Workflow(
        id="wf-builder001",
        name="builder-demo",
        description="d",
        inputs=(WorkflowInput(name="url"),),
        stages=(),
        builder="fake",
    )


def _store_with(workflow: Workflow, tmp_path: Path) -> WorkflowStore:
    """Throwaway store with one workflow saved (runs need the FK row)."""
    store = WorkflowStore(tmp_path / "workflows.db")
    store.save(replace(workflow, created_at=_STAMP, updated_at=_STAMP))
    return store


def test_builder_workflow_validates(monkeypatch: pytest.MonkeyPatch) -> None:
    _register_fake(monkeypatch)
    assert validate(_builder_workflow()) == []
    assert ensure_valid(_builder_workflow()) is not None


def test_unknown_builder_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    _register_fake(monkeypatch)
    problems = validate(replace(_builder_workflow(), builder="nope"))
    assert any("unknown builder" in problem for problem in problems)


def test_bad_builder_name_reports_regex(monkeypatch: pytest.MonkeyPatch) -> None:
    _register_fake(monkeypatch)
    problems = validate(replace(_builder_workflow(), builder="Bad Name"))
    assert any("must match" in problem for problem in problems)


def test_no_stages_no_builder_still_reports(monkeypatch: pytest.MonkeyPatch) -> None:
    _register_fake(monkeypatch)
    problems = validate(replace(_builder_workflow(), builder=None))
    assert any("workflow has no stages" in problem for problem in problems)


def test_yaml_round_trip_keeps_builder_no_stages_key(monkeypatch: pytest.MonkeyPatch) -> None:
    _register_fake(monkeypatch)
    workflow = _builder_workflow()
    text = to_yaml(workflow)
    assert "stages" not in yaml.safe_load(text)
    assert from_yaml(text) == replace(workflow, id="")


def test_yaml_unknown_builder_raises() -> None:
    text = "fleet_workflow: 1\nname: x\nbuilder: nope\n"
    with pytest.raises(WorkflowInvalid):
        from_yaml(text)


def test_start_run_expands_builder(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _register_fake(monkeypatch)
    workflow = _builder_workflow()
    store = _store_with(workflow, tmp_path)
    queue = RecordingQueue()
    run = start_run(
        workflow,
        store=store,
        queue=queue,
        now=datetime.fromisoformat(_AT),
        trigger=Trigger.manual,
        inputs={"url": "https://example.test/x"},
    )
    assert len(queue.creates) == 2
    saved = store.get_run(run.id)
    assert saved is not None
    assert len(saved.spec.stages) == 1
    assert [step.name for step in saved.spec.stages[0].steps] == ["a", "b"]
    assert saved.spec.builder is None
    assert queue.creates[0]["title"] == "A https://example.test/x"


def test_start_run_builder_error_raises_no_bead(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _register_fake(monkeypatch)

    def _boom(workflow: Workflow, ctx: builders.BuildContext) -> Workflow:
        _ = (workflow, ctx)
        raise SourceError("boom")

    monkeypatch.setattr(fake_builder, "build", _boom)
    workflow = _builder_workflow()
    store = _store_with(workflow, tmp_path)
    queue = RecordingQueue()
    with pytest.raises(WorkflowInvalid):
        start_run(
            workflow,
            store=store,
            queue=queue,
            now=datetime.fromisoformat(_AT),
            trigger=Trigger.manual,
            inputs={"url": "https://example.test/x"},
        )
    assert queue.creates == []


def test_print_workflow_show_prints_builder(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _register_fake(monkeypatch)
    print_workflow_show(_builder_workflow())
    out = capsys.readouterr().out
    assert "builder:" in out
    assert "fake" in out


def test_plain_workflow_unaffected(tmp_path: Path) -> None:
    """A workflow without a builder still plans its own stages (no registry)."""
    workflow = _plain_workflow()
    store = WorkflowStore(tmp_path / "workflows.db")
    store.save(replace(workflow, created_at=_STAMP, updated_at=_STAMP))
    queue = FakeQueue()
    run = start_run(
        workflow,
        store=store,
        queue=queue,
        now=datetime.fromisoformat(_AT),
        trigger=Trigger.manual,
    )
    assert len(store.step_runs(run.id)) == 3
