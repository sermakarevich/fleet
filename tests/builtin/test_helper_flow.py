"""Tests for the helper flow and the fleet_blocked tool (builtin catalog)."""

from __future__ import annotations

from typing import Any

from fleet.flows import folders
from fleet.flows.templates import render
from fleet.flows.tools import command_for

_EXPECTED_INPUTS = {
    "id",
    "title",
    "blocked_reason",
    "blocked_at",
    "cwd",
    "coder",
    "model",
    "rounds",
    "result_status",
    "task_dir",
    "stderr_tail",
}

_REQUIRED_INPUTS = {"id", "title", "blocked_reason", "blocked_at"}


def _context() -> dict[str, Any]:
    """Fake run context mirroring runs/state.context for the helper flow."""
    inputs = {
        "id": "fleet-abc",
        "title": "Fix login redirect",
        "blocked_reason": "retry limit (3) exhausted",
        "blocked_at": "2026-09-28T10:00:00+00:00",
        "cwd": "/repo",
        "coder": "claude",
        "model": "opus",
        "rounds": "{'failure': 3}",
        "result_status": "",
        "task_dir": "/home/u/.fleet/tasks/fleet-abc",
        "stderr_tail": "boom",
    }
    steps = {
        "investigate": {
            "outputs": {
                "root_cause": "Disk full.",
                "fixes": ["Free space.", "Add disk."],
                "same_as_previous": "no",
            },
            "items": [],
            "status": "succeeded",
            "checks": {},
            "item_checks": [],
        },
        "approve": {
            "outputs": {"answer": "Free space.", "note": ""},
            "items": [],
            "status": "succeeded",
            "checks": {},
            "item_checks": [],
        },
        "apply": {
            "outputs": {},
            "items": [],
            "status": "pending",
            "checks": {},
            "item_checks": [],
        },
    }
    return {
        "inputs": inputs,
        "run": {"id": "run-20260928-x", "date": "2026-09-28", "flow": "helper"},
        "defaults": {
            "coder": "claude",
            "model": "opus",
            "cwd": "{{ inputs.cwd }}",
            "isolation": "worktree",
        },
        "steps": steps,
    }


def test_helper_flow_parses_disabled_with_tool_start() -> None:
    """helper.yaml is present, disabled, and polled from fleet_blocked."""
    catalog = folders.load(["builtin"])
    assert catalog.problems == []
    flow = catalog.flows["helper"]
    assert flow.enabled is False
    assert flow.on.tool is not None
    assert flow.on.tool.name == "fleet_blocked"
    assert flow.on.tool.every == "1m"
    assert flow.on.manual is True


def test_helper_start_key_renders_to_id_at_blocked_at() -> None:
    """The start key renders one run per block event (id@blocked_at)."""
    catalog = folders.load(["builtin"])
    flow = catalog.flows["helper"]
    assert flow.on.tool is not None
    key = render(
        flow.on.tool.key,
        {"item": {"id": "fleet-abc", "blocked_at": "2026-09-28T10:00:00+00:00"}},
    )
    assert key == "fleet-abc@2026-09-28T10:00:00+00:00"


def test_helper_inputs_are_eleven_with_four_required() -> None:
    """The flow declares the eleven blocked-listing keys; four are required."""
    catalog = folders.load(["builtin"])
    flow = catalog.flows["helper"]
    assert {item.name for item in flow.inputs} == _EXPECTED_INPUTS
    assert {item.name for item in flow.inputs if item.required} == _REQUIRED_INPUTS
    for item in flow.inputs:
        if not item.required:
            assert item.default == ""


def test_helper_defaults_pin_coder_model_cwd_isolation() -> None:
    """Defaults carry the helper coder/model plus the rendered cwd and worktree."""
    catalog = folders.load(["builtin"])
    flow = catalog.flows["helper"]
    assert flow.defaults["coder"] == "claude"
    assert flow.defaults["model"] == "opus"
    assert flow.defaults["cwd"] == "{{ inputs.cwd }}"
    assert flow.defaults["isolation"] == "worktree"


def test_helper_steps_chain_investigate_approve_apply() -> None:
    """investigate (coder) -> approve (human) -> apply (coder) with declared outputs."""
    catalog = folders.load(["builtin"])
    flow = catalog.flows["helper"]
    assert [step.name for step in flow.steps] == ["investigate", "approve", "apply"]
    investigate, approve, apply = flow.steps
    assert investigate.kind == "coder"
    assert tuple(investigate.outputs) == ("root_cause", "fixes", "same_as_previous")
    assert approve.kind == "human"
    assert approve.needs == ("investigate",)
    assert tuple(approve.outputs) == ("answer", "note")
    assert apply.kind == "coder"
    assert apply.needs == ("approve",)


def test_helper_prompts_render_over_fake_context() -> None:
    """Every step prompt renders with no leftover templates, naming bead and verdicts."""
    catalog = folders.load(["builtin"])
    flow = catalog.flows["helper"]
    ctx = _context()
    rendered = {step.name: render(step.prompt, ctx) for step in flow.steps}
    for text in rendered.values():
        assert "{{" not in text
    assert "fleet-abc" in rendered["investigate"]
    assert "HELPER_REPORT.md" in rendered["investigate"]
    assert "outputs/outputs.json" in rendered["investigate"]
    assert "Disk full." in rendered["approve"]
    assert "1. Free space." in rendered["approve"]
    assert "close the original task" in rendered["approve"]
    assert "Free space." in rendered["apply"]
    assert "fleet-abc" in rendered["apply"]
    assert "bd comment" in rendered["apply"]


def test_fleet_blocked_tool_polls_blocked_json() -> None:
    """fleet_blocked runs `fleet blocked --json` with a 60s timeout."""
    catalog = folders.load(["builtin"])
    assert catalog.problems == []
    tool = catalog.tools["fleet_blocked"]
    assert tool.output == "json"
    assert tool.timeout == 60
    assert "helper" in tool.description
    assert command_for(tool, {}) == ["fleet", "blocked", "--json"]
