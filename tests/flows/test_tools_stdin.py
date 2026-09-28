"""Tests for Tool.stdin, Tool.dir, and stdin_for in fleet.flows.tools."""

from __future__ import annotations

from typing import Any

import pytest

from fleet.core.errors import FlowInvalid
from fleet.flows import tools


def _valid_data() -> dict[str, Any]:
    """Build a valid tool mapping with a stdin template."""
    return {
        "fleet_tool": 2,
        "description": "Classify text into labels.",
        "command": ["jev", "choose", "{{ args.labels }}", "-s", "-"],
        "args": {
            "labels": {"required": True, "description": "Comma-separated labels."},
            "state": {"required": True, "description": "Text to classify."},
        },
        "env": [],
        "output": "json",
        "timeout": 60,
        "stdin": "{{ args.state }}",
    }


def test_stdin_round_trips() -> None:
    """stdin survives tool_from_dict / tool_to_dict and rebuilds equally."""
    tool = tools.tool_from_dict(_valid_data(), "jev_choose", source="/tmp/t/jev_choose.yaml")
    assert tool.stdin == "{{ args.state }}"
    dumped = tools.tool_to_dict(tool)
    assert dumped["stdin"] == "{{ args.state }}"
    rebuilt = tools.tool_from_dict(dumped, tool.name, source=tool.source)
    assert rebuilt == tool


def test_stdin_must_be_a_string() -> None:
    """A non-string stdin is rejected with its message."""
    data = _valid_data()
    data["stdin"] = 42
    with pytest.raises(FlowInvalid, match="stdin: must be a string"):
        tools.tool_from_dict(data, "jev_choose")


def test_stdin_for_renders_args() -> None:
    """stdin_for renders the stdin template over resolved args."""
    tool = tools.tool_from_dict(_valid_data(), "jev_choose")
    assert tools.stdin_for(tool, {"labels": "a,b", "state": "hello"}) == "hello"


def test_stdin_for_none_when_unset() -> None:
    """Tools without stdin render None."""
    data = _valid_data()
    del data["stdin"]
    tool = tools.tool_from_dict(data, "jev_choose")
    assert tool.stdin is None
    assert tools.stdin_for(tool, {"labels": "a,b", "state": "hello"}) is None
    assert "stdin" not in tools.tool_to_dict(tool)


def test_dir_derived_from_source() -> None:
    """tool.dir is the parent folder of source, or empty without one."""
    tool = tools.tool_from_dict(_valid_data(), "jev_choose", source="/tmp/t/jev_choose.yaml")
    assert tool.dir == "/tmp/t"
    assert tools.tool_from_dict(_valid_data(), "jev_choose").dir == ""


def test_dir_usable_in_command() -> None:
    """{{ tool.dir }} renders to the tool file's folder in command."""
    data = _valid_data()
    data["command"] = ["python3", "{{ tool.dir }}/x.py", "{{ args.state }}"]
    tool = tools.tool_from_dict(data, "runner", source="/tmp/t/runner.yaml")
    argv = tools.command_for(tool, {"labels": "a,b", "state": "hi"})
    assert argv == ["python3", "/tmp/t/x.py", "hi"]


def test_dir_never_in_tool_to_dict() -> None:
    """dir is provenance, not YAML: it never appears in tool_to_dict."""
    tool = tools.tool_from_dict(_valid_data(), "jev_choose", source="/tmp/t/jev_choose.yaml")
    assert tool.dir == "/tmp/t"
    assert "dir" not in tools.tool_to_dict(tool)


def test_describe_for_prompt_mentions_stdin() -> None:
    """The prompt block carries the stdin template when set."""
    text = tools.describe_for_prompt(tools.tool_from_dict(_valid_data(), "jev_choose"))
    assert "args.state" in text
