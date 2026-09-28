"""Tests for fleet.flows.model."""

from __future__ import annotations

from typing import Any

import pytest

from fleet.core.errors import FlowInvalid
from fleet.flows.model import (
    FLOW_VERSION,
    STEP_KINDS,
    STEP_WHEN,
    WHEN_FAILED,
    WHEN_FINISHED,
    WHEN_OK,
    flow_from_dict,
    flow_to_dict,
)


def _valid_data() -> dict[str, Any]:
    """A valid flow dict exercising every field group."""
    return {
        "fleet_flow": 2,
        "description": "Autonomous coding of one feature.",
        "enabled": True,
        "on": {
            "manual": True,
            "cron": {"expr": "0 7 * * 1-5", "tz": "Europe/Berlin"},
            "tool": {
                "name": "bd_ready",
                "args": {"label": "ready"},
                "every": "1m",
                "key": "{{ item.id }}",
            },
        },
        "inputs": {
            "repo": {"description": "Target repo.", "required": True},
            "auto": {"description": "Skip gates.", "default": "off"},
        },
        "defaults": {"coder": "opencode", "model": "opencode-go/muse-spark", "retries": 2},
        "steps": {
            "requirements": {
                "prompt": "Write requirements.",
                "coder": "opencode",
                "model": "opencode-go/muse-spark",
                "cwd": "{{ inputs.repo }}",
                "isolation": "worktree",
                "retries": 2,
                "tools": ["pytest"],
                "outputs": ["units"],
            },
            "implement": {
                "needs": ["requirements"],
                "for_each": "{{ steps.requirements.outputs.units }}",
                "key": "{{ item.unit }}",
                "after": "{{ item.after }}",
                "parallel": "{{ steps.requirements.outputs.flag }}",
                "model": "{{ item.model }}",
                "prompt": "Implement {{ item.unit }}.",
            },
            "gate": {
                "needs": ["implement"],
                "kind": "human",
                "prompt": "Continue?",
                "skip_if": "{{ inputs.auto == 'on' }}",
            },
            "commit": {
                "needs": ["implement"],
                "kind": "tool",
                "tool": "git_commit",
                "args": {"paths": "docs/"},
            },
        },
    }


def _problems(data: dict[str, Any], name: str = "autocode") -> list[str]:
    """Parse an invalid dict and return every reported problem."""
    with pytest.raises(FlowInvalid) as excinfo:
        flow_from_dict(data, name)
    return excinfo.value.problems


def test_version_and_kinds() -> None:
    """Module constants match the spec."""
    assert FLOW_VERSION == 2
    assert STEP_KINDS == ("coder", "human", "tool")


def test_valid_flow_parses_all_fields() -> None:
    """Every field survives parsing with its value intact."""
    flow = flow_from_dict(_valid_data(), "autocode", source="flows/autocode.yaml")

    assert flow.name == "autocode"
    assert flow.source == "flows/autocode.yaml"
    assert flow.description == "Autonomous coding of one feature."
    assert flow.enabled is True
    assert flow.on.manual is True
    assert flow.on.cron is not None and flow.on.cron.expr == "0 7 * * 1-5"
    assert flow.on.cron.tz == "Europe/Berlin"
    assert flow.on.tool is not None and flow.on.tool.name == "bd_ready"
    assert flow.on.tool.args == {"label": "ready"}
    assert flow.on.tool.every == "1m"
    assert flow.inputs[0].name == "repo" and flow.inputs[0].required is True
    assert flow.inputs[1].default == "off"
    assert flow.defaults["coder"] == "opencode"
    assert [step.name for step in flow.steps] == [
        "requirements",
        "implement",
        "gate",
        "commit",
    ]
    assert flow.step("gate").kind == "human"
    assert flow.step("commit").tool == "git_commit"
    assert flow.step("implement").for_each == "{{ steps.requirements.outputs.units }}"
    with pytest.raises(KeyError):
        flow.step("missing")


def test_valid_flow_round_trips() -> None:
    """Flow -> dict -> Flow preserves the parsed value."""
    flow = flow_from_dict(_valid_data(), "autocode", source="flows/autocode.yaml")
    refeeds = flow_from_dict(flow_to_dict(flow), "autocode")
    assert refeeds.name == flow.name
    assert refeeds.description == flow.description
    assert refeeds.on == flow.on
    assert refeeds.inputs == flow.inputs
    assert refeeds.defaults == flow.defaults
    assert refeeds.steps == flow.steps
    assert refeeds.enabled == flow.enabled


def test_minimal_flow_uses_defaults() -> None:
    """A one-step flow parses with every default in place."""
    flow = flow_from_dict({"fleet_flow": 2, "steps": {"build": {"prompt": "Do it."}}}, "tiny")
    assert flow.description == ""
    assert flow.enabled is True
    assert flow.on.manual is True and flow.on.cron is None and flow.on.tool is None
    assert flow.inputs == () and flow.defaults == {}
    assert flow.step("build").kind == "coder"
    assert flow.step("build").parallel is True


def test_missing_fleet_flow() -> None:
    """A missing version marker is rejected."""
    data = _valid_data()
    del data["fleet_flow"]
    assert "fleet_flow: must be 2" in _problems(data)


def test_wrong_fleet_flow() -> None:
    """A version other than 2 is rejected."""
    data = _valid_data()
    data["fleet_flow"] = 1
    assert "fleet_flow: must be 2" in _problems(data)


def test_missing_steps() -> None:
    """A flow without steps is rejected."""
    data = _valid_data()
    del data["steps"]
    assert "steps: must be a non-empty mapping" in _problems(data)


def test_empty_steps() -> None:
    """A flow with an empty steps mapping is rejected."""
    data = _valid_data()
    data["steps"] = {}
    assert "steps: must be a non-empty mapping" in _problems(data)


def test_bad_step_kind() -> None:
    """An unknown step kind is rejected."""
    data = _valid_data()
    data["steps"]["gate"]["kind"] = "wizard"
    assert "step gate: kind must be one of coder, human, tool" in _problems(data)


def test_needs_unknown_step() -> None:
    """A need pointing at no step is rejected."""
    data = _valid_data()
    data["steps"]["gate"]["needs"] = ["ghost"]
    assert "step gate: needs unknown step ghost" in _problems(data)


def test_needs_itself() -> None:
    """A step needing itself is rejected."""
    data = _valid_data()
    data["steps"]["gate"]["needs"] = ["gate"]
    assert "step gate: needs itself" in _problems(data)


def test_cycle() -> None:
    """A needs cycle names the steps in the cycle."""
    data = _valid_data()
    data["steps"] = {
        "alpha": {"prompt": "A.", "needs": ["beta"]},
        "beta": {"prompt": "B.", "needs": ["alpha"]},
    }
    problems = _problems(data)
    assert "steps: cycle through alpha -> beta -> alpha" in problems


def test_coder_requires_prompt() -> None:
    """A coder step without a prompt is rejected."""
    data = _valid_data()
    data["steps"]["requirements"]["prompt"] = "   "
    assert "step requirements: kind coder requires prompt" in _problems(data)


def test_human_requires_prompt() -> None:
    """A human step without a question is rejected."""
    data = _valid_data()
    del data["steps"]["gate"]["prompt"]
    assert "step gate: kind human requires prompt" in _problems(data)


def test_tool_requires_tool() -> None:
    """A tool step without a tool name is rejected."""
    data = _valid_data()
    del data["steps"]["commit"]["tool"]
    assert "step commit: kind tool requires tool" in _problems(data)


def test_key_requires_for_each() -> None:
    """A key without for_each is rejected."""
    data = _valid_data()
    del data["steps"]["implement"]["for_each"]
    assert "step implement: key requires for_each" in _problems(data)


def test_after_requires_for_each() -> None:
    """An after without for_each is rejected."""
    data = _valid_data()
    data["steps"]["requirements"]["after"] = "{{ item.after }}"
    assert "step requirements: after requires for_each" in _problems(data)


def test_step_unknown_field() -> None:
    """An unknown step key is rejected."""
    data = _valid_data()
    data["steps"]["gate"]["bogus"] = 1
    assert "step gate: unknown field bogus" in _problems(data)


def test_input_default_and_required_exclusive() -> None:
    """An input cannot be both required and defaulted."""
    data = _valid_data()
    data["inputs"]["repo"]["default"] = "somewhere"
    assert "input repo: default and required are exclusive" in _problems(data)


def test_on_tool_requires_name() -> None:
    """A tool start without a name is rejected."""
    data = _valid_data()
    assert isinstance(data["on"], dict)
    data["on"]["tool"] = {"every": "1m"}
    assert "on.tool: requires name" in _problems(data)


def test_on_cron_requires_expr() -> None:
    """A cron start without an expression is rejected."""
    data = _valid_data()
    assert isinstance(data["on"], dict)
    data["on"]["cron"] = {"tz": "Europe/Berlin"}
    assert "on.cron: requires expr" in _problems(data)


def test_bad_flow_name() -> None:
    """A flow name outside [a-z][a-z0-9_-]* is rejected."""
    assert "name: must match [a-z][a-z0-9_-]*" in _problems(_valid_data(), name="Bad name!")


def test_bad_step_name() -> None:
    """A step name outside [a-z][a-z0-9_-]* is rejected."""
    data = _valid_data()
    data["steps"] = {"Bad": {"prompt": "Hi."}}
    assert "name: must match [a-z][a-z0-9_-]*" in _problems(data)


def test_bad_input_name() -> None:
    """An input name outside [a-z][a-z0-9_-]* is rejected."""
    data = _valid_data()
    data["inputs"] = {"Bad": {"required": True}}
    assert "name: must match [a-z][a-z0-9_-]*" in _problems(data)


def test_unknown_top_level_field() -> None:
    """An unknown top-level key is rejected."""
    data = _valid_data()
    data["bogus_top"] = 1
    assert "unknown field bogus_top" in _problems(data)


def test_several_problems_reported_together() -> None:
    """One raise carries every problem found across the file."""
    data = _valid_data()
    del data["fleet_flow"]
    data["bogus_top"] = 1
    data["steps"]["gate"]["kind"] = "wizard"
    data["inputs"]["repo"]["default"] = "somewhere"
    problems = _problems(data)
    assert "fleet_flow: must be 2" in problems
    assert "unknown field bogus_top" in problems
    assert "step gate: kind must be one of coder, human, tool" in problems
    assert "input repo: default and required are exclusive" in problems
    assert len(problems) >= 4


def test_step_order_follows_dict_order() -> None:
    """Steps keep file order, not sorted order."""
    data = _valid_data()
    data["steps"] = {
        "zzz": {"prompt": "Z."},
        "mmm": {"prompt": "M."},
        "aaa": {"prompt": "A."},
    }
    flow = flow_from_dict(data, "ordered")
    assert [step.name for step in flow.steps] == ["zzz", "mmm", "aaa"]


def test_when_values_match_spec() -> None:
    """The when constants are exactly ok, failed and finished."""
    assert WHEN_OK == "ok"
    assert WHEN_FAILED == "failed"
    assert WHEN_FINISHED == "finished"
    assert STEP_WHEN == ("ok", "failed", "finished")


def test_when_defaults_to_ok() -> None:
    """A step without when parses as ok."""
    flow = flow_from_dict({"fleet_flow": 2, "steps": {"build": {"prompt": "Do it."}}}, "tiny")
    assert flow.step("build").when == "ok"


def test_when_parses_and_round_trips() -> None:
    """Non-default when values survive parsing and the dict round-trip."""
    data = _valid_data()
    data["steps"]["gate"]["needs"] = ["requirements"]
    data["steps"]["gate"]["when"] = "failed"
    data["steps"]["commit"]["when"] = "finished"
    flow = flow_from_dict(data, "autocode")
    assert flow.step("gate").when == "failed"
    assert flow.step("commit").when == "finished"
    refeeds = flow_from_dict(flow_to_dict(flow), "autocode")
    assert refeeds.steps == flow.steps
    assert flow_to_dict(flow)["steps"]["gate"]["when"] == "failed"


def test_when_ok_omitted_from_dict() -> None:
    """The default when is omitted when a step is serialized."""
    flow = flow_from_dict({"fleet_flow": 2, "steps": {"build": {"prompt": "Do it."}}}, "tiny")
    assert "when" not in flow_to_dict(flow)["steps"]["build"]


def test_bad_when_value() -> None:
    """A when outside ok, failed, finished is rejected."""
    data = _valid_data()
    data["steps"]["gate"]["needs"] = ["requirements"]
    data["steps"]["gate"]["when"] = "sometimes"
    assert "step gate: when must be one of ok, failed, finished" in _problems(data)


def test_when_failed_without_needs() -> None:
    """when failed or finished with no needs is rejected."""
    data = _valid_data()
    data["steps"]["requirements"]["when"] = "failed"
    assert "step requirements: when needs at least one need" in _problems(data)
    data["steps"]["requirements"]["when"] = "finished"
    assert "step requirements: when needs at least one need" in _problems(data)
