"""Tests for the `research` builder: description text, the single epic step, input checks."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from fleet.workflows.builders import BuildContext
from fleet.workflows.builders.research import DEFINITION, build, description_for
from fleet.workflows.model import Defaults, Workflow, ensure_valid
from fleet.workflows.planning import metadata_for


def _ctx(tmp_path: Path, **inputs: str) -> BuildContext:
    return BuildContext(
        run_id="wfr-r0000001",
        fleet_home=tmp_path,
        now=datetime(2026, 9, 22, tzinfo=UTC),
        inputs=inputs,
    )


def _workflow() -> Workflow:
    return Workflow(
        id="wf-resear01",
        name="research",
        description="d",
        defaults=Defaults(cwd="/kb", priority=1),
        builder="research",
    )


_FULL = {
    "topics": "voice-agents",
    "focus": "SOTA of voice agents",
    "target": "voiceagents",
    "n_sources": "150",
    "lenses": "business, product, tech, ai",
    "gate": "on",
    "date_from": "2026-03-22",
    "kinds": "all",
}


def test_description_for_lists_every_input_as_key_value() -> None:
    text = description_for(_FULL)
    assert "ai show research/get" in text
    for key, value in _FULL.items():
        assert f"{key}: {value}" in text


def test_description_for_fills_defaults_and_skips_blank_optionals() -> None:
    text = description_for({"topics": "t", "focus": "f", "target": "slug", "date_from": ""})
    assert "n_sources: 10" in text
    assert "lenses: tech, ai" in text
    assert "gate: on" in text
    assert "date_from" not in text
    assert "kinds" not in text


def test_build_returns_one_epic_step_with_research_worker(tmp_path: Path) -> None:
    built = build(_workflow(), _ctx(tmp_path, **_FULL))
    assert [stage.name for stage in built.stages] == ["research"]
    (step,) = built.stages[0].steps
    assert step.name == "epic"
    assert step.worker == "research"
    assert step.title.startswith("research: voice-agents")
    assert "target: voiceagents" in step.description
    assert ensure_valid(built) is built
    assert metadata_for(built.id, "wfr-r0000001", step)["fleet_worker"] == "research"


@pytest.mark.parametrize("missing", ["topics", "focus", "target"])
def test_build_rejects_missing_required_input(tmp_path: Path, missing: str) -> None:
    inputs = {**_FULL, missing: "  "}
    with pytest.raises(ValueError, match=missing):
        build(_workflow(), _ctx(tmp_path, **inputs))


@pytest.mark.parametrize("target", ["a/b", "/abs", "..", "."])
def test_build_rejects_target_paths(tmp_path: Path, target: str) -> None:
    with pytest.raises(ValueError, match="slug"):
        build(_workflow(), _ctx(tmp_path, **{**_FULL, "target": target}))


def test_definition_inputs_match_required_keys() -> None:
    required = {item["name"] for item in DEFINITION["inputs"] if item.get("required")}
    assert required == {"topics", "focus", "target"}
    assert DEFINITION["name"] == "research"
