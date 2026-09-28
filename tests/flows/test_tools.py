"""Tests for fleet.flows.tools."""

from __future__ import annotations

from typing import Any

import pytest

from fleet.core.errors import FlowInvalid
from fleet.flows import tools
from fleet.flows.tools import Tool, ToolArg


def _valid_data() -> dict[str, Any]:
    """Build a valid tool mapping shaped like tools/x_tweet.yaml."""
    return {
        "fleet_tool": 2,
        "description": "Parse a tweet or thread with the x CLI.",
        "command": ["x", "tweet", "{{ args.url }}", "--thread", "--format", "json"],
        "args": {
            "url": {"required": True, "description": "Tweet URL to parse."},
            "limit": {"description": "Max tweets.", "default": "10"},
        },
        "env": ["TWITTERAPI_IO_KEY"],
        "output": "json",
        "timeout": 120,
    }


def test_valid_tool_round_trips() -> None:
    """tool_to_dict output parses back into an equal Tool."""
    tool = tools.tool_from_dict(_valid_data(), "x_tweet", source="tools/x_tweet.yaml")
    assert tool.name == "x_tweet"
    assert tool.source == "tools/x_tweet.yaml"
    assert isinstance(tool.command, tuple)
    assert isinstance(tool.args, tuple)
    assert isinstance(tool.env, tuple)
    rebuilt = tools.tool_from_dict(tools.tool_to_dict(tool), tool.name, source=tool.source)
    assert rebuilt == tool


def test_bad_version_problem() -> None:
    """A wrong fleet_tool version is rejected with its message."""
    data = _valid_data()
    data["fleet_tool"] = 1
    with pytest.raises(FlowInvalid, match="fleet_tool: must be 2"):
        tools.tool_from_dict(data, "x_tweet")


def test_missing_version_problem() -> None:
    """A missing fleet_tool key is rejected with its message."""
    data = _valid_data()
    del data["fleet_tool"]
    with pytest.raises(FlowInvalid, match="fleet_tool: must be 2"):
        tools.tool_from_dict(data, "x_tweet")


@pytest.mark.parametrize("command", [[], "x tweet", [1, 2], ["x", 42]])
def test_bad_command_problem(command: Any) -> None:
    """Empty, non-list, or non-string commands are rejected with their message."""
    data = _valid_data()
    data["command"] = command
    with pytest.raises(FlowInvalid, match="command: must be a non-empty list of strings"):
        tools.tool_from_dict(data, "x_tweet")


def test_bad_output_problem() -> None:
    """An unknown output kind is rejected with its message."""
    data = _valid_data()
    data["output"] = "yaml"
    with pytest.raises(FlowInvalid, match="output: must be one of json, lines, text"):
        tools.tool_from_dict(data, "x_tweet")


@pytest.mark.parametrize("timeout", [0, -5, "60", 1.5, True])
def test_bad_timeout_problem(timeout: Any) -> None:
    """Non-positive or non-int timeouts are rejected with their message."""
    data = _valid_data()
    data["timeout"] = timeout
    with pytest.raises(FlowInvalid, match="timeout: must be a positive integer"):
        tools.tool_from_dict(data, "x_tweet")


def test_exclusive_default_and_required_problem() -> None:
    """An arg with both default and required is rejected with its message."""
    data = _valid_data()
    data["args"] = {"url": {"required": True, "default": "https://x.example/"}}
    with pytest.raises(FlowInvalid, match=r"arg url: default and required are exclusive"):
        tools.tool_from_dict(data, "x_tweet")


def test_unknown_field_problem() -> None:
    """An unexpected top-level key is rejected naming the key."""
    data = _valid_data()
    data["shell"] = True
    with pytest.raises(FlowInvalid, match="unknown field shell"):
        tools.tool_from_dict(data, "x_tweet")


@pytest.mark.parametrize("name", ["Bad", "1tool", "", "has space", "UPPER"])
def test_bad_name_problem(name: str) -> None:
    """Names outside [a-z][a-z0-9_-]* are rejected with their message."""
    with pytest.raises(FlowInvalid, match=r"name: must match \[a-z\]"):
        tools.tool_from_dict(_valid_data(), name)


def test_problems_collect() -> None:
    """Several independent problems surface together in .problems."""
    data = _valid_data()
    data["fleet_tool"] = 1
    data["output"] = "yaml"
    with pytest.raises(FlowInvalid) as excinfo:
        tools.tool_from_dict(data, "x_tweet")
    assert len(excinfo.value.problems) >= 2


def test_missing_env_reports_unset_and_empty() -> None:
    """Unset or empty env names are reported; set ones are not."""
    tool = tools.tool_from_dict(_valid_data(), "x_tweet")
    assert tools.missing_env(tool, {}) == ["TWITTERAPI_IO_KEY"]
    assert tools.missing_env(tool, {"TWITTERAPI_IO_KEY": ""}) == ["TWITTERAPI_IO_KEY"]
    assert tools.missing_env(tool, {"TWITTERAPI_IO_KEY": "secret"}) == []


def test_resolve_args_fills_default() -> None:
    """Optional args fall back to their declared default."""
    tool = tools.tool_from_dict(_valid_data(), "x_tweet")
    resolved = tools.resolve_args(tool, {"url": "https://x.example/1"})
    assert resolved == {"url": "https://x.example/1", "limit": "10"}


def test_resolve_args_missing_required() -> None:
    """A missing required arg raises naming the argument."""
    tool = tools.tool_from_dict(_valid_data(), "x_tweet")
    with pytest.raises(FlowInvalid, match="arg url: required"):
        tools.resolve_args(tool, {"limit": "5"})


def test_resolve_args_unknown() -> None:
    """An undeclared arg name raises naming the argument."""
    tool = tools.tool_from_dict(_valid_data(), "x_tweet")
    with pytest.raises(FlowInvalid, match="arg bogus: unknown"):
        tools.resolve_args(tool, {"url": "https://x.example/1", "bogus": "x"})


def test_command_for_renders_one_element_without_splitting() -> None:
    """Only the templated element changes; spaces in values stay one element."""
    tool = Tool(
        name="echoer",
        command=("echo", "{{ args.message }}", "--format", "json"),
        args=(ToolArg(name="message", required=True),),
    )
    argv = tools.command_for(tool, {"message": "hello world"})
    assert argv == ["echo", "hello world", "--format", "json"]


def test_command_for_uses_default() -> None:
    """Declared defaults flow into the rendered argv."""
    tool = tools.tool_from_dict(_valid_data(), "x_tweet")
    argv = tools.command_for(tool, {"url": "https://x.example/1"})
    assert argv[2] == "https://x.example/1"


def test_parse_output_json() -> None:
    """json output parses into Python values."""
    tool = Tool(name="fetcher", output="json")
    assert tools.parse_output(tool, '{"items": [1, 2]}') == {"items": [1, 2]}


def test_parse_output_bad_json() -> None:
    """Invalid JSON raises naming the failure."""
    tool = Tool(name="fetcher", output="json")
    with pytest.raises(FlowInvalid, match="output: not valid JSON"):
        tools.parse_output(tool, "not json{")


def test_parse_output_lines() -> None:
    """lines output strips whitespace and drops blank lines."""
    tool = Tool(name="lister", output="lines")
    assert tools.parse_output(tool, "  alpha\n\nbeta  \n \n") == ["alpha", "beta"]


def test_parse_output_text() -> None:
    """text output returns stdout unchanged."""
    tool = Tool(name="catter", output="text")
    assert tools.parse_output(tool, "  raw\n  text  \n") == "  raw\n  text  \n"


def test_describe_for_prompt_contains_name_command_and_args() -> None:
    """The prompt block names the tool, its command, and every arg."""
    tool = tools.tool_from_dict(_valid_data(), "x_tweet")
    text = tools.describe_for_prompt(tool)
    assert "x_tweet" in text
    assert "x tweet" in text
    assert "url" in text
    assert "limit" in text
    assert "required" in text
    assert "optional" in text
    assert "10" in text
