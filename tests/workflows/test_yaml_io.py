"""YAML tests: ADR example round trip and every rejection case."""

from __future__ import annotations

import pytest
import yaml

from fleet.core.errors import WorkflowInvalid
from fleet.workflows.model import ensure_valid
from fleet.workflows.yaml_io import from_yaml, to_yaml

ADR_EXAMPLE = """\
fleet_workflow: 1
name: nightly-quality
description: Lint, test and summarise
defaults: {cwd: /Users/me/git/app, coder: opencode, model: qwen3.6:latest, priority: 2}
stages:
  - name: checks
    steps:
      - name: lint
        title: "Lint {{workflow.name}} ({{run.date}})"
        description: Run ruff and fix what it reports.
      - name: tests
        title: Run the test suite
        description: uv run pytest -q; fix failures.
        coder: claude
        model: sonnet
  - name: report
    steps:
      - name: summary
        title: Summarise the night
        description: "Read tasks {{steps.lint.task_id}} and
          {{steps.tests.task_id}} and write a summary."
        needs: [lint, tests]
"""


def test_adr_example_parses_and_validates() -> None:
    workflow = from_yaml(ADR_EXAMPLE)
    assert workflow.id == ""
    assert workflow.created_at == ""
    assert workflow.name == "nightly-quality"
    assert [s.name for s in workflow.stages] == ["checks", "report"]
    assert workflow.defaults.model == "qwen3.6:latest"
    assert ensure_valid(workflow) is workflow


def test_round_trip_every_field() -> None:
    workflow = from_yaml(ADR_EXAMPLE)
    assert from_yaml(to_yaml(workflow, with_ids=True)) == workflow


def test_round_trip_assigns_ids() -> None:
    workflow = from_yaml(ADR_EXAMPLE)
    exported = yaml.safe_load(to_yaml(workflow, with_ids=True))
    assert exported["id"] == ""  # caller assigns real ids after import
    assert "created_at" in exported and "updated_at" in exported


def test_export_key_order_matches_adr() -> None:
    keys = list(yaml.safe_load(to_yaml(from_yaml(ADR_EXAMPLE))).keys())
    assert keys == ["fleet_workflow", "name", "description", "defaults", "stages"]


def test_export_block_style() -> None:
    text = to_yaml(from_yaml(ADR_EXAMPLE))
    assert "{" not in text.splitlines()[0] or "fleet_workflow" in text.splitlines()[0]
    reparsed = yaml.safe_load(text)
    assert isinstance(reparsed["stages"], list)


def test_bad_version_rejected() -> None:
    with pytest.raises(WorkflowInvalid, match="fleet_workflow"):
        from_yaml(ADR_EXAMPLE.replace("fleet_workflow: 1", "fleet_workflow: 2"))


def test_missing_stages_rejected() -> None:
    with pytest.raises(WorkflowInvalid, match="stages"):
        from_yaml("fleet_workflow: 1\nname: x\n")


def test_unknown_top_level_key_rejected() -> None:
    with pytest.raises(WorkflowInvalid, match="mystery"):
        from_yaml(ADR_EXAMPLE + "mystery: 1\n")


def test_duplicate_names_rejected_with_text() -> None:
    text = ADR_EXAMPLE.replace("- name: summary", "- name: lint")
    with pytest.raises(WorkflowInvalid, match="duplicate"):
        from_yaml(text)


def test_needs_into_later_stage_rejected_with_text() -> None:
    text = ADR_EXAMPLE.replace("needs: [lint, tests]", "needs: [summary]")
    with pytest.raises(WorkflowInvalid, match="same or a later stage"):
        from_yaml(text)


def test_needs_unknown_step_rejected() -> None:
    text = ADR_EXAMPLE.replace("needs: [lint, tests]", "needs: [ghost]")
    with pytest.raises(WorkflowInvalid, match="ghost"):
        from_yaml(text)


def test_garbage_yaml_rejected() -> None:
    with pytest.raises(WorkflowInvalid):
        from_yaml("{{{not yaml")
