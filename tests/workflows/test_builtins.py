"""Built-in workflow registration on fleet start."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from fleet.workflows.builtins import (
    builtin_definitions,
    ensure_builtin_workflows,
    workflow_from_definition,
)
from fleet.workflows.model import Workflow, ensure_valid
from fleet.workflows.store import WorkflowStore

_NOW = datetime(2026, 9, 22, 9, 0, tzinfo=UTC)


def test_builtin_definitions_cover_research_and_summarise() -> None:
    names = {definition["name"] for _, definition in builtin_definitions()}
    assert {"research", "summarise"} <= names


def test_workflow_from_definition_is_valid_builder_workflow() -> None:
    for builder, definition in builtin_definitions():
        wf = workflow_from_definition(builder, definition, _NOW)
        assert wf.builder == builder
        assert wf.stages == ()
        assert wf.id.startswith("wf-")
        assert ensure_valid(wf) is wf


def test_ensure_builtin_workflows_adds_once_and_keeps_edits(tmp_path: Path) -> None:
    store = WorkflowStore(tmp_path / "w.db")
    added = ensure_builtin_workflows(store, _NOW)
    assert "research" in added
    assert store.get_by_name("research") is not None

    # Second start: nothing added, operator edits survive.
    saved = store.get_by_name("research")
    assert saved is not None
    store.save(replace(saved, description="edited by operator"))
    assert ensure_builtin_workflows(store, _NOW) == []
    again = store.get_by_name("research")
    assert again is not None
    assert again.description == "edited by operator"
    assert again.id == saved.id


def test_ensure_builtin_backfills_missing_optional_inputs(tmp_path: Path) -> None:
    """Older saved workflows gain new optional inputs without losing edits."""
    store = WorkflowStore(tmp_path / "w.db")
    ensure_builtin_workflows(store, _NOW)
    saved = store.get_by_name("summarise")
    assert saved is not None
    assert "research_target" in {item.name for item in saved.inputs}

    # Simulate an install saved before research_target existed.
    assert isinstance(saved, Workflow)
    stripped = replace(
        saved,
        inputs=tuple(item for item in saved.inputs if item.name != "research_target"),
        description="edited by operator",
    )
    store.save(stripped)
    assert "research_target" not in {
        item.name for item in store.get_by_name("summarise").inputs  # type: ignore[union-attr]
    }

    assert ensure_builtin_workflows(store, _NOW) == []
    refilled = store.get_by_name("summarise")
    assert refilled is not None
    names = [item.name for item in refilled.inputs]
    assert "research_target" in names
    # Operator edits survive; old inputs keep order, backfill appends.
    assert refilled.description == "edited by operator"
    assert names.index("url") < names.index("research_target")
    backfilled = next(item for item in refilled.inputs if item.name == "research_target")
    assert backfilled.required is False
