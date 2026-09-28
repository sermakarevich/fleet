"""Tests for the shipped builtin tools and the bead flow (no subprocess runs)."""

from __future__ import annotations

from fleet.flows import folders
from fleet.flows.tools import command_for, stdin_for

_EXPECTED_OUTPUTS = {
    "pytest": "text",
    "ruff": "text",
    "git_commit_paths": "text",
    "jev_choose": "json",
    "jev_check": "json",
    "bd_ready": "json",
    "bd_blocked": "json",
    "bd_close": "text",
    "bd_block": "text",
    "worktree_merge": "json",
    "worktree_drop": "json",
}


def test_builtin_loads_without_problems() -> None:
    """load(["builtin"]) reports no problems."""
    catalog = folders.load(["builtin"])
    assert catalog.problems == []


def test_builtin_tools_present_with_declared_outputs() -> None:
    """Every shipped tool is present with its declared output kind."""
    catalog = folders.load(["builtin"])
    assert set(_EXPECTED_OUTPUTS) <= set(catalog.tools)
    for name, output in _EXPECTED_OUTPUTS.items():
        assert catalog.tools[name].output == output


def test_bead_flow_parses_with_work_and_close() -> None:
    """The bead flow has work and close steps started by the bd_ready tool."""
    catalog = folders.load(["builtin"])
    flow = catalog.flows["bead"]
    assert flow.on.tool is not None
    assert flow.on.tool.name == "bd_ready"
    assert [step.name for step in flow.steps] == ["work", "close"]
    assert flow.step("close").tool == "bd_close"


def test_jev_choose_renders_without_templates() -> None:
    """command_for renders every argv element; stdin_for returns the state."""
    catalog = folders.load(["builtin"])
    tool = catalog.tools["jev_choose"]
    argv = command_for(
        tool,
        {"question": "Which team?", "a": "billing", "b": "tech", "state": "My invoice is wrong"},
    )
    assert argv == [
        "jev",
        "choose",
        "Which team?",
        "-o",
        "billing",
        "-o",
        "tech",
        "-s",
        "-",
        "--format",
        "json",
    ]
    assert all("{{" not in element for element in argv)
    assert stdin_for(tool, {"question": "q", "a": "x", "b": "y", "state": "hello"}) == "hello"
