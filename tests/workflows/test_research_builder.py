"""Tests for the `research` builder: description text, the single epic step, input checks."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from fleet.workflows.builders import BuildContext
from fleet.workflows.builders import topics as topics_mod
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


@pytest.fixture()
def topics_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Fake research_topics/ with two topics; build() validates against it."""
    base = tmp_path / "research_topics"
    (base / "voice_agents").mkdir(parents=True)
    (base / "coding_agents").mkdir(parents=True)
    monkeypatch.setattr(topics_mod, "research_topics_dir", lambda: base)
    return base


_FULL = {
    "topics": "voice-agents",
    "focus": "SOTA of voice agents",
    "target": "voiceagents",
    "topic": "voice_agents",
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
    text = description_for(
        {"topics": "t", "focus": "f", "target": "slug", "topic": "voice_agents", "date_from": ""}
    )
    assert "n_sources: 10" in text
    assert "lenses: tech, ai" in text
    assert "gate: on" in text
    assert "topic: voice_agents" in text
    assert "date_from" not in text
    assert "kinds" not in text


def test_build_returns_one_epic_step_with_research_worker(
    tmp_path: Path, topics_dir: Path
) -> None:
    built = build(_workflow(), _ctx(tmp_path, **_FULL))
    assert [stage.name for stage in built.stages] == ["research"]
    (step,) = built.stages[0].steps
    assert step.name == "epic"
    assert step.worker == "research"
    assert step.title.startswith("research: voice-agents")
    assert "target: voiceagents" in step.description
    assert "topic: voice_agents" in step.description
    assert ensure_valid(built) is built
    assert metadata_for(built.id, "wfr-r0000001", step)["fleet_worker"] == "research"


@pytest.mark.parametrize("missing", ["topics", "focus", "target", "topic"])
def test_build_rejects_missing_required_input(
    tmp_path: Path, topics_dir: Path, missing: str
) -> None:
    inputs = {**_FULL, missing: "  "}
    with pytest.raises(ValueError, match=missing):
        build(_workflow(), _ctx(tmp_path, **inputs))


@pytest.mark.parametrize("target", ["a/b", "/abs", "..", "."])
def test_build_rejects_target_paths(tmp_path: Path, topics_dir: Path, target: str) -> None:
    with pytest.raises(ValueError, match="slug"):
        build(_workflow(), _ctx(tmp_path, **{**_FULL, "target": target}))


@pytest.mark.parametrize("topic", ["VoiceAgents", "voice-agents", "voice agents", "a/b", ""])
def test_build_rejects_non_snake_case_topic(
    tmp_path: Path, topics_dir: Path, topic: str
) -> None:
    with pytest.raises(ValueError, match="[Ss]nake_case|required"):
        build(_workflow(), _ctx(tmp_path, **{**_FULL, "topic": topic}))


def test_build_rejects_unknown_topic_with_existing_list(
    tmp_path: Path, topics_dir: Path
) -> None:
    with pytest.raises(ValueError, match="ai new nosuch_topic") as exc_info:
        build(_workflow(), _ctx(tmp_path, **{**_FULL, "topic": "nosuch_topic"}))
    message = str(exc_info.value)
    assert "voice_agents" in message
    assert "coding_agents" in message


def test_definition_inputs_match_required_keys() -> None:
    required = {item["name"] for item in DEFINITION["inputs"] if item.get("required")}
    assert required == {"topics", "focus", "target", "topic"}
    assert DEFINITION["name"] == "research"


def test_definition_kinds_uses_discover_vocabulary() -> None:
    kinds = next(item for item in DEFINITION["inputs"] if item["name"] == "kinds")
    for word in ("paper", "article", "video", "repo", "thread"):
        assert word in kinds["description"]
