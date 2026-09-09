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


INPUTS_EXAMPLE = """\
fleet_workflow: 1
name: paper-summary
description: Summarise a paper.
inputs:
  - name: paper_url
    description: URL of the paper.
    required: true
  - name: focus
    default: methods
defaults: {coder: opencode, priority: 2}
stages:
  - name: read
    steps:
      - name: fetch
        title: "Fetch {{inputs.paper_url}}"
        description: "Focus on {{inputs.focus}}."
  - name: file
    steps:
      - name: file-note
        title: File the note
        description: Runs in place.
        isolation: none
"""


def test_inputs_and_isolation_parse() -> None:
    workflow = from_yaml(INPUTS_EXAMPLE)
    assert [(item.name, item.required, item.default) for item in workflow.inputs] == [
        ("paper_url", True, None),
        ("focus", False, "methods"),
    ]
    assert workflow.inputs[0].description == "URL of the paper."
    assert workflow.stages[1].steps[0].isolation == "none"
    assert workflow.stages[0].steps[0].isolation is None


def test_inputs_and_isolation_round_trip() -> None:
    workflow = from_yaml(INPUTS_EXAMPLE)
    assert from_yaml(to_yaml(workflow)) == workflow


def test_export_omits_unset_inputs_and_isolation() -> None:
    exported = yaml.safe_load(to_yaml(from_yaml(ADR_EXAMPLE)))
    assert "inputs" not in exported
    assert "isolation" not in exported["defaults"]
    steps = [step for stage in exported["stages"] for step in stage["steps"]]
    assert all("isolation" not in step for step in steps)


def test_export_key_order_with_inputs() -> None:
    keys = list(yaml.safe_load(to_yaml(from_yaml(INPUTS_EXAMPLE))).keys())
    assert keys == ["fleet_workflow", "name", "description", "defaults", "inputs", "stages"]


def test_bad_isolation_rejected() -> None:
    text = INPUTS_EXAMPLE.replace("isolation: none", "isolation: vault")
    with pytest.raises(WorkflowInvalid, match="isolation"):
        from_yaml(text)


def test_inputs_must_be_a_list() -> None:
    text = (
        "fleet_workflow: 1\nname: x\ninputs: {paper_url: x}\n"
        "stages:\n  - name: s\n    steps:\n      - name: a\n        title: A\n"
    )
    with pytest.raises(WorkflowInvalid, match="inputs"):
        from_yaml(text)


def test_required_input_with_default_rejected() -> None:
    text = INPUTS_EXAMPLE.replace("required: true", "required: true\n    default: x")
    with pytest.raises(WorkflowInvalid, match="default"):
        from_yaml(text)
