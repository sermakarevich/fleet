"""Tests for checks in fleet.flows.model (DESIGN.md §3.8)."""

from __future__ import annotations

from typing import Any

import pytest

from fleet.core.errors import FlowInvalid
from fleet.flows.model import (
    CHECK_KINDS,
    CHECK_WHEN,
    ON_FAIL,
    effective_checks,
    flow_from_dict,
    flow_to_dict,
)


def _base(checks: Any = None, defaults_checks: Any = None) -> dict[str, Any]:
    """A minimal flow dict with optional step and defaults checks."""
    step: dict[str, Any] = {"prompt": "Draft a reply."}
    if checks is not None:
        step["checks"] = checks
    data: dict[str, Any] = {"fleet_flow": 2, "steps": {"draft": step}}
    if defaults_checks is not None:
        data["defaults"] = {"checks": defaults_checks}
    return data


def _problems(data: dict[str, Any]) -> list[str]:
    """Parse an invalid dict and return every reported problem."""
    with pytest.raises(FlowInvalid) as excinfo:
        flow_from_dict(data, "autocode")
    return excinfo.value.problems


def test_constants() -> None:
    """Check constants match the spec."""
    assert CHECK_KINDS == ("tool", "coder", "human")
    assert CHECK_WHEN == ("before", "after")
    assert ON_FAIL == ("retry", "fail", "skip", "stop")


def test_three_kinds_inferred() -> None:
    """DESIGN §3.8 kinds are inferred from tool:/coder:/prompt:."""
    flow = flow_from_dict(
        _base(
            [
                {
                    "name": "fresh",
                    "tool": "reply_dedupe",
                    "args": {"reply": "{{ outputs.reply }}", "days": "3"},
                    "on_fail": "retry",
                },
                {
                    "name": "judge",
                    "coder": "opencode",
                    "prompt": "Is this reply good?",
                },
                {"name": "confirm", "prompt": "Post this reply?"},
            ]
        ),
        "autocode",
    )
    kinds = [check.kind for check in flow.step("draft").checks]
    assert kinds == ["tool", "coder", "human"]


def test_model_with_prompt_infers_coder() -> None:
    """A model: plus prompt check infers kind coder."""
    flow = flow_from_dict(_base([{"name": "j", "model": "m", "prompt": "Q?"}]), "a")
    assert flow.step("draft").checks[0].kind == "coder"


def test_defaults_checks_parsed() -> None:
    """defaults.checks lands in default_checks, not in defaults."""
    flow = flow_from_dict(
        _base(defaults_checks=[{"name": "lint", "tool": "pytest", "on_fail": "retry"}]),
        "autocode",
    )
    assert [check.name for check in flow.default_checks] == ["lint"]
    assert "checks" not in flow.defaults


def test_effective_checks_coder_gets_defaults() -> None:
    """Coder steps see defaults plus their own checks, in order."""
    flow = flow_from_dict(
        {
            "fleet_flow": 2,
            "defaults": {"checks": [{"name": "lint", "tool": "pytest"}]},
            "steps": {
                "draft": {
                    "prompt": "Draft.",
                    "checks": [{"name": "fresh", "tool": "dedupe"}],
                }
            },
        },
        "autocode",
    )
    assert [c.name for c in effective_checks(flow, flow.step("draft"))] == [
        "lint",
        "fresh",
    ]


def test_effective_checks_tool_ignores_defaults() -> None:
    """Tool steps see only their own checks."""
    flow = flow_from_dict(
        {
            "fleet_flow": 2,
            "defaults": {"checks": [{"name": "lint", "tool": "pytest"}]},
            "steps": {
                "run": {
                    "kind": "tool",
                    "tool": "pytest",
                    "checks": [{"name": "fresh", "tool": "dedupe"}],
                }
            },
        },
        "autocode",
    )
    assert [c.name for c in effective_checks(flow, flow.step("run"))] == ["fresh"]


def test_effective_checks_empty_list_opts_out() -> None:
    """An explicit checks: [] disables defaults for coder steps."""
    flow = flow_from_dict(
        {
            "fleet_flow": 2,
            "defaults": {"checks": [{"name": "lint", "tool": "pytest"}]},
            "steps": {"draft": {"prompt": "Draft.", "checks": []}},
        },
        "autocode",
    )
    assert flow.step("draft").checks_set is True
    assert effective_checks(flow, flow.step("draft")) == ()


def test_bad_kind() -> None:
    """An unknown check kind is rejected."""
    data = _base([{"name": "c", "kind": "wizard", "tool": "t"}])
    assert "step draft check 0: kind must be one of tool, coder, human" in _problems(data)


def test_bad_when() -> None:
    """An unknown check hook point is rejected."""
    data = _base([{"name": "c", "tool": "t", "when": "during"}])
    assert "step draft check 0: when must be one of before, after" in _problems(data)


def test_bad_on_fail() -> None:
    """An unknown on_fail is rejected."""
    data = _base([{"name": "c", "tool": "t", "on_fail": "explode"}])
    assert "step draft check 0: on_fail must be one of retry, fail, skip, stop" in _problems(data)


def test_tool_required() -> None:
    """A tool check without a tool is rejected."""
    assert "step draft check 0: tool is required for kind tool" in _problems(
        _base([{"name": "c", "kind": "tool"}])
    )


def test_prompt_required_coder() -> None:
    """A coder check without a prompt is rejected."""
    data = _base([{"name": "c", "kind": "coder", "coder": "opencode"}])
    assert "step draft check 0: prompt is required for kind coder" in _problems(data)


def test_prompt_required_human() -> None:
    """A human check without a prompt is rejected."""
    data = _base([{"name": "c", "kind": "human"}])
    assert "step draft check 0: prompt is required for kind human" in _problems(data)


def test_unknown_field() -> None:
    """An unknown check key is rejected."""
    data = _base([{"name": "c", "tool": "t", "bogus": 1}])
    assert "step draft check 0: unknown field bogus" in _problems(data)


def test_checks_must_be_a_list() -> None:
    """A non-list checks value is rejected."""
    assert "step draft: checks must be a list" in _problems(_base({"oops": 1}))


def test_defaults_label() -> None:
    """defaults.checks problems use the defaults label."""
    data = _base(defaults_checks={"oops": 1})
    assert "defaults: checks must be a list" in _problems(data)


def test_args_values_must_be_strings() -> None:
    """Non-string check args values are rejected."""
    data = _base([{"name": "c", "tool": "t", "args": {"days": 3}}])
    problems = _problems(data)
    assert "step draft check 0: args: value for 'days' must be a string" in problems


def test_duplicate_names() -> None:
    """Duplicate check names within one step are rejected."""
    data = _base([{"name": "c", "tool": "t"}, {"name": "c", "tool": "u"}])
    assert "step draft: check names must be unique" in _problems(data)


def test_before_retry_rejected() -> None:
    """on_fail retry on a before check is rejected."""
    data = _base([{"name": "c", "tool": "t", "when": "before", "on_fail": "retry"}])
    assert "step draft check 0: before checks cannot retry" in _problems(data)


def test_several_problems_collected() -> None:
    """One raise carries every check problem found."""
    data = _base(
        [
            {"name": "c", "kind": "wizard", "tool": "t"},
            {"name": "c", "tool": "t", "when": "during"},
        ]
    )
    problems = _problems(data)
    assert "step draft check 0: kind must be one of tool, coder, human" in problems
    assert "step draft check 1: when must be one of before, after" in problems
    assert "step draft: check names must be unique" in problems
    assert len(problems) >= 3


def test_round_trip() -> None:
    """A flow with checks and defaults.checks serializes back exactly."""
    data: dict[str, Any] = {
        "fleet_flow": 2,
        "defaults": {
            "checks": [
                {
                    "name": "lint",
                    "tool": "pytest",
                    "args": {"target": "tests/"},
                    "on_fail": "retry",
                }
            ]
        },
        "steps": {
            "draft": {
                "prompt": "Draft a reply.",
                "checks": [
                    {
                        "name": "fresh",
                        "tool": "reply_dedupe",
                        "args": {"reply": "{{ outputs.reply }}"},
                        "on_fail": "retry",
                    },
                    {
                        "name": "post",
                        "kind": "human",
                        "prompt": "Post this reply?",
                        "on_fail": "skip",
                    },
                ],
            }
        },
    }
    assert flow_to_dict(flow_from_dict(data, "autocode")) == data
