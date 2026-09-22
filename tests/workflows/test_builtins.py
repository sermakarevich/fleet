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
from fleet.workflows.model import ensure_valid
from fleet.workflows.store import WorkflowStore

_NOW = datetime(2026, 9, 22, 9, 0, tzinfo=UTC)


def test_builtin_definitions_cover_research_and_summary_get() -> None:
    names = {definition["name"] for _, definition in builtin_definitions()}
    assert {"research", "summary_get"} <= names


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
