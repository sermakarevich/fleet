"""Fleet 2 flow file model: frozen dataclasses, parsing and validation.

Parses the YAML shape from ``docs/27_sep_upgrade/DESIGN.md`` §3.2 into frozen
dataclasses. ``flow_from_dict`` collects every problem and raises ``FlowInvalid``
once; ``flow_to_dict`` is its inverse (without ``name`` and ``source``).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from fleet.core.errors import FlowInvalid

STEP_KINDS: tuple[str, ...] = ("coder", "human", "tool")
"""Allowed ``Step.kind`` values (DESIGN.md §3.1)."""

FLOW_VERSION = 2
"""Value the ``fleet_flow`` key must carry."""

_NAME_PATTERN = re.compile(r"[a-z][a-z0-9_-]*")
_NAME_MESSAGE = "name: must match [a-z][a-z0-9_-]*"

_TOP_LEVEL_FIELDS = frozenset(
    {"fleet_flow", "description", "enabled", "on", "inputs", "defaults", "steps"}
)

_STEP_FIELDS = frozenset(
    {
        "name",
        "kind",
        "needs",
        "prompt",
        "tool",
        "args",
        "tools",
        "coder",
        "model",
        "cwd",
        "isolation",
        "retries",
        "for_each",
        "key",
        "after",
        "parallel",
        "skip_if",
        "outputs",
    }
)


@dataclass(frozen=True)
class Input:
    """One named flow input with its requirement rule."""

    name: str
    description: str = ""
    required: bool = False
    default: str | None = None


@dataclass(frozen=True)
class Cron:
    """A cron start: 5-field expression plus timezone."""

    expr: str
    tz: str = "UTC"


@dataclass(frozen=True)
class ToolStart:
    """A tool start: poll a tool, each new item starts a run."""

    name: str
    args: dict[str, str] = field(default_factory=dict)
    every: str = "5m"
    key: str = "{{ item.id }}"


@dataclass(frozen=True)
class On:
    """What starts a flow: cron time, polled tool, or a person."""

    cron: Cron | None = None
    tool: ToolStart | None = None
    manual: bool = True


@dataclass(frozen=True)
class Step:
    """One step of a flow: a coder launch, a human question, or a tool run."""

    name: str
    kind: str = "coder"
    needs: tuple[str, ...] = ()
    prompt: str = ""
    tool: str | None = None
    args: dict[str, str] = field(default_factory=dict)
    tools: tuple[str, ...] = ()
    coder: str | None = None
    model: str | None = None
    cwd: str | None = None
    isolation: str | None = None
    retries: int | str | None = None
    for_each: str | None = None
    key: str | None = None
    after: str | None = None
    parallel: bool | str = True
    skip_if: str | None = None
    outputs: tuple[str, ...] = ()


@dataclass(frozen=True)
class Flow:
    """One parsed flow file: inputs, defaults and steps in file order."""

    name: str
    description: str = ""
    on: On = field(default_factory=On)
    inputs: tuple[Input, ...] = ()
    defaults: dict[str, Any] = field(default_factory=dict)
    steps: tuple[Step, ...] = ()
    enabled: bool = True
    source: str = ""

    def step(self, step_name: str) -> Step:
        """Return the step with this name, raising KeyError when missing."""
        for candidate in self.steps:
            if candidate.name == step_name:
                return candidate
        raise KeyError(step_name)


def flow_from_dict(data: Mapping[str, Any], name: str, source: str = "") -> Flow:
    """Parse a decoded flow file, raising FlowInvalid with every problem found."""
    problems: list[str] = []
    if not isinstance(data, Mapping):
        raise FlowInvalid(["flow: must be a mapping"])
    for top_key in data:
        if top_key not in _TOP_LEVEL_FIELDS:
            problems.append(f"unknown field {top_key}")
    if data.get("fleet_flow") != FLOW_VERSION:
        problems.append("fleet_flow: must be 2")
    if not (isinstance(name, str) and _NAME_PATTERN.fullmatch(name)):
        problems.append(_NAME_MESSAGE)
    description = _parse_description(data.get("description"), problems)
    enabled = _parse_enabled(data.get("enabled", True), problems)
    flow_on = _parse_on(data.get("on"), problems)
    inputs = _parse_inputs(data.get("inputs"), problems)
    defaults = _parse_defaults(data.get("defaults"), problems)
    steps = _parse_steps(data.get("steps"), problems)
    if problems:
        raise FlowInvalid(problems)
    return Flow(
        name=name,
        description=description,
        on=flow_on,
        inputs=inputs,
        defaults=defaults,
        steps=steps,
        enabled=enabled,
        source=source,
    )


def flow_to_dict(flow: Flow) -> dict[str, Any]:
    """Serialize a Flow back to its YAML-ready mapping (without name/source)."""
    data: dict[str, Any] = {"fleet_flow": FLOW_VERSION}
    if flow.description:
        data["description"] = flow.description
    if not flow.enabled:
        data["enabled"] = flow.enabled
    if flow.on != On():
        data["on"] = _on_to_dict(flow.on)
    if flow.inputs:
        data["inputs"] = {item.name: _input_to_dict(item) for item in flow.inputs}
    if flow.defaults:
        data["defaults"] = dict(flow.defaults)
    data["steps"] = {step.name: _step_to_dict(step) for step in flow.steps}
    return data


def _parse_description(raw_value: Any, problems: list[str]) -> str:
    """Read the optional description, defaulting to empty on misuse."""
    if raw_value is None:
        return ""
    if not isinstance(raw_value, str):
        problems.append("description: must be a string")
        return ""
    return raw_value


def _parse_enabled(raw_value: Any, problems: list[str]) -> bool:
    """Read the enabled flag, defaulting to True on misuse."""
    if not isinstance(raw_value, bool):
        problems.append("enabled: must be a bool")
        return True
    return raw_value


def _parse_on(raw_on: Any, problems: list[str]) -> On:
    """Validate the `on:` mapping, recording problems."""
    if raw_on is None:
        return On()
    if not isinstance(raw_on, Mapping):
        problems.append("on: must be a mapping")
        return On()
    manual: Any = raw_on.get("manual", True)
    if not isinstance(manual, bool):
        problems.append("on.manual: must be a bool")
        manual = True
    return On(
        cron=_parse_cron(raw_on.get("cron"), problems),
        tool=_parse_tool_start(raw_on.get("tool"), problems),
        manual=manual,
    )


def _parse_cron(raw_cron: Any, problems: list[str]) -> Cron | None:
    """Validate the `on.cron` mapping, recording problems."""
    if raw_cron is None:
        return None
    if not isinstance(raw_cron, Mapping):
        problems.append("on.cron: must be a mapping")
        return None
    expr = raw_cron.get("expr")
    if not isinstance(expr, str) or not expr:
        problems.append("on.cron: requires expr")
        return None
    timezone = raw_cron.get("tz", "UTC")
    if not isinstance(timezone, str) or not timezone:
        problems.append("on.cron.tz: must be a string")
        timezone = "UTC"
    return Cron(expr=expr, tz=timezone)


def _parse_tool_start(raw_tool: Any, problems: list[str]) -> ToolStart | None:
    """Validate the `on.tool` mapping, recording problems."""
    if raw_tool is None:
        return None
    if not isinstance(raw_tool, Mapping):
        problems.append("on.tool: must be a mapping")
        return None
    tool_name = raw_tool.get("name")
    if not isinstance(tool_name, str) or not tool_name:
        problems.append("on.tool: requires name")
        return None
    every = raw_tool.get("every", "5m")
    if not isinstance(every, str) or not every:
        problems.append(f"on.tool {tool_name}: every must be a non-empty string")
        every = "5m"
    key = raw_tool.get("key", "{{ item.id }}")
    if not isinstance(key, str) or not key:
        problems.append(f"on.tool {tool_name}: key must be a non-empty string")
        key = "{{ item.id }}"
    args = _parse_str_map(raw_tool.get("args"), f"on.tool {tool_name}: args", problems)
    return ToolStart(name=tool_name, args=args, every=every, key=key)


def _parse_str_map(raw_map: Any, label: str, problems: list[str]) -> dict[str, str]:
    """Read a string-to-string mapping, recording problems for bad values."""
    if raw_map is None:
        return {}
    if not isinstance(raw_map, Mapping):
        problems.append(f"{label}: must be a mapping")
        return {}
    parsed: dict[str, str] = {}
    for map_key, map_value in raw_map.items():
        if not isinstance(map_value, str):
            problems.append(f"{label}: value for {map_key!r} must be a string")
            continue
        parsed[str(map_key)] = map_value
    return parsed


def _parse_inputs(raw_inputs: Any, problems: list[str]) -> tuple[Input, ...]:
    """Validate the `inputs:` mapping, recording problems."""
    if raw_inputs is None:
        return ()
    if not isinstance(raw_inputs, Mapping):
        problems.append("inputs: must be a mapping")
        return ()
    return tuple(
        _parse_input(input_name, raw_item, problems) for input_name, raw_item in raw_inputs.items()
    )


def _parse_input(input_name: Any, raw_item: Any, problems: list[str]) -> Input:
    """Validate one input entry, recording problems."""
    label = input_name if isinstance(input_name, str) else repr(input_name)
    if not (isinstance(input_name, str) and _NAME_PATTERN.fullmatch(input_name)):
        problems.append(_NAME_MESSAGE)
    if not isinstance(raw_item, Mapping):
        problems.append(f"input {label}: must be a mapping")
        raw_item = {}
    description = raw_item.get("description", "")
    if not isinstance(description, str):
        problems.append(f"input {label}: description must be a string")
        description = ""
    required = raw_item.get("required", False)
    if not isinstance(required, bool):
        problems.append(f"input {label}: required must be a bool")
        required = bool(required)
    default = raw_item.get("default")
    if required and default is not None:
        problems.append(f"input {label}: default and required are exclusive")
    if default is not None and not isinstance(default, str):
        problems.append(f"input {label}: default must be a string")
        default = None
    resolved = input_name if isinstance(input_name, str) else str(input_name)
    return Input(name=resolved, description=description, required=required, default=default)


def _parse_defaults(raw_defaults: Any, problems: list[str]) -> dict[str, Any]:
    """Read the `defaults:` mapping, defaulting to empty on misuse."""
    if raw_defaults is None:
        return {}
    if not isinstance(raw_defaults, Mapping):
        problems.append("defaults: must be a mapping")
        return {}
    return dict(raw_defaults)


def _parse_steps(raw_steps: Any, problems: list[str]) -> tuple[Step, ...]:
    """Validate the `steps:` mapping, keeping file order, recording problems."""
    if not isinstance(raw_steps, Mapping) or not raw_steps:
        problems.append("steps: must be a non-empty mapping")
        return ()
    step_names = list(raw_steps)
    needs_map: dict[str, list[str]] = {}
    parsed = [
        _parse_step(step_name, raw_step, step_names, problems, needs_map)
        for step_name, raw_step in raw_steps.items()
    ]
    problems.extend(_cycle_problems(step_names, needs_map))
    return tuple(parsed)


def _parse_step(
    step_name: Any,
    raw_step: Any,
    step_names: list[Any],
    problems: list[str],
    needs_map: dict[str, list[str]],
) -> Step:
    """Validate one step entry, recording problems and its needs edges."""
    label = step_name if isinstance(step_name, str) else repr(step_name)
    if not (isinstance(step_name, str) and _NAME_PATTERN.fullmatch(step_name)):
        problems.append(_NAME_MESSAGE)
    if not isinstance(raw_step, Mapping):
        problems.append(f"step {label}: must be a mapping")
        needs_map[label] = []
        return Step(name=str(label))
    for step_key in raw_step:
        if step_key == "name":
            continue
        if step_key not in _STEP_FIELDS:
            problems.append(f"step {label}: unknown field {step_key}")
    kind = raw_step.get("kind", "coder")
    if kind not in STEP_KINDS:
        problems.append(f"step {label}: kind must be one of coder, human, tool")
    needs = _parse_needs(label, step_name, raw_step.get("needs", []), step_names, problems)
    needs_map[label] = needs
    prompt = raw_step.get("prompt", "")
    if not isinstance(prompt, str):
        problems.append(f"step {label}: prompt must be a string")
        prompt = ""
    if kind in ("coder", "human") and not prompt.strip():
        problems.append(f"step {label}: kind {kind} requires prompt")
    tool_name = raw_step.get("tool")
    if kind == "tool" and (not isinstance(tool_name, str) or not tool_name):
        problems.append(f"step {label}: kind tool requires tool")
    for_each = _parse_optional_str(raw_step.get("for_each"), f"step {label}", "for_each", problems)
    key = _parse_optional_str(raw_step.get("key"), f"step {label}", "key", problems)
    after = _parse_optional_str(raw_step.get("after"), f"step {label}", "after", problems)
    if key is not None and for_each is None:
        problems.append(f"step {label}: key requires for_each")
    if after is not None and for_each is None:
        problems.append(f"step {label}: after requires for_each")
    return Step(
        name=str(label),
        kind=kind if isinstance(kind, str) else "coder",
        needs=tuple(needs),
        prompt=prompt,
        tool=tool_name if isinstance(tool_name, str) and tool_name else None,
        args=_parse_str_map(raw_step.get("args"), f"step {label}: args", problems),
        tools=_parse_str_list(raw_step.get("tools"), f"step {label}: tools", problems),
        coder=_parse_optional_str(raw_step.get("coder"), f"step {label}", "coder", problems),
        model=_parse_optional_str(raw_step.get("model"), f"step {label}", "model", problems),
        cwd=_parse_optional_str(raw_step.get("cwd"), f"step {label}", "cwd", problems),
        isolation=_parse_optional_str(
            raw_step.get("isolation"), f"step {label}", "isolation", problems
        ),
        retries=_parse_retries(raw_step.get("retries"), f"step {label}", problems),
        for_each=for_each,
        key=key,
        after=after,
        parallel=_parse_parallel(raw_step.get("parallel", True), f"step {label}", problems),
        skip_if=_parse_optional_str(raw_step.get("skip_if"), f"step {label}", "skip_if", problems),
        outputs=_parse_str_list(raw_step.get("outputs"), f"step {label}: outputs", problems),
    )


def _parse_needs(
    label: Any,
    step_name: Any,
    raw_needs: Any,
    step_names: list[Any],
    problems: list[str],
) -> list[str]:
    """Validate a step's needs list, recording unknown and self edges."""
    if raw_needs is None:
        return []
    if not isinstance(raw_needs, (list, tuple)):
        problems.append(f"step {label}: needs must be a list")
        return []
    needs: list[str] = []
    for need in raw_needs:
        if not isinstance(need, str):
            problems.append(f"step {label}: needs entries must be strings")
            continue
        if need == step_name:
            problems.append(f"step {label}: needs itself")
        elif need not in step_names:
            problems.append(f"step {label}: needs unknown step {need}")
        needs.append(need)
    return needs


def _parse_optional_str(
    raw_value: Any, label: str, field_name: str, problems: list[str]
) -> str | None:
    """Read an optional string field, recording problems for other types."""
    if raw_value is None:
        return None
    if not isinstance(raw_value, str):
        problems.append(f"{label}: {field_name} must be a string")
        return None
    return raw_value


def _parse_str_list(raw_value: Any, label: str, problems: list[str]) -> tuple[str, ...]:
    """Read an optional list of strings, recording problems for bad entries."""
    if raw_value is None:
        return ()
    if not isinstance(raw_value, (list, tuple)):
        problems.append(f"{label} must be a list")
        return ()
    items: list[str] = []
    for entry in raw_value:
        if not isinstance(entry, str):
            problems.append(f"{label} entries must be strings")
            continue
        items.append(entry)
    return tuple(items)


def _parse_retries(raw_value: Any, label: str, problems: list[str]) -> int | str | None:
    """Read the retries field: an int or a template, recording misuse."""
    if raw_value is None or isinstance(raw_value, str):
        return raw_value
    if isinstance(raw_value, bool) or not isinstance(raw_value, int):
        problems.append(f"{label}: retries must be an int or a template")
        return None
    return raw_value


def _parse_parallel(raw_value: Any, label: str, problems: list[str]) -> bool | str:
    """Read the parallel field: a bool or a template, defaulting to True."""
    if isinstance(raw_value, (bool, str)):
        return raw_value
    problems.append(f"{label}: parallel must be a bool or a template")
    return True


def _cycle_problems(step_names: list[Any], needs_map: dict[str, list[str]]) -> list[str]:
    """Report one problem per needs cycle, naming the steps in the cycle."""
    problems: list[str] = []
    done: set[str] = set()
    for root in step_names:
        _visit_cycle(root, needs_map, done, [], problems)
    return problems


def _visit_cycle(
    node: Any,
    needs_map: dict[str, list[str]],
    done: set[str],
    trail: list[str],
    problems: list[str],
) -> None:
    """Depth-first search for back edges, appending one problem per cycle."""
    label = str(node)
    if label in trail:
        cycle = trail[trail.index(label) :] + [label]
        problems.append(f"steps: cycle through {' -> '.join(cycle)}")
        return
    if label in done:
        return
    trail.append(label)
    for dependency in needs_map.get(label, []):
        if dependency in needs_map:
            _visit_cycle(dependency, needs_map, done, trail, problems)
    trail.pop()
    done.add(label)


def _on_to_dict(flow_on: On) -> dict[str, Any]:
    """Serialize an On back to its mapping form."""
    data: dict[str, Any] = {"manual": flow_on.manual}
    if flow_on.cron is not None:
        data["cron"] = {"expr": flow_on.cron.expr, "tz": flow_on.cron.tz}
    if flow_on.tool is not None:
        tool_data: dict[str, Any] = {"name": flow_on.tool.name}
        if flow_on.tool.args:
            tool_data["args"] = dict(flow_on.tool.args)
        tool_data["every"] = flow_on.tool.every
        tool_data["key"] = flow_on.tool.key
        data["tool"] = tool_data
    return data


def _input_to_dict(item: Input) -> dict[str, Any]:
    """Serialize an Input back to its mapping form."""
    data: dict[str, Any] = {}
    if item.description:
        data["description"] = item.description
    if item.required:
        data["required"] = item.required
    if item.default is not None:
        data["default"] = item.default
    return data


def _step_to_dict(step: Step) -> dict[str, Any]:
    """Serialize a Step back to its mapping form, omitting defaults."""
    data: dict[str, Any] = {}
    if step.kind != "coder":
        data["kind"] = step.kind
    if step.needs:
        data["needs"] = list(step.needs)
    if step.prompt:
        data["prompt"] = step.prompt
    if step.tool is not None:
        data["tool"] = step.tool
    if step.args:
        data["args"] = dict(step.args)
    if step.tools:
        data["tools"] = list(step.tools)
    for field_name in (
        "coder",
        "model",
        "cwd",
        "isolation",
        "retries",
        "for_each",
        "key",
        "after",
        "skip_if",
    ):
        value = getattr(step, field_name)
        if value is not None:
            data[field_name] = value
    if step.parallel is not True:
        data["parallel"] = step.parallel
    if step.outputs:
        data["outputs"] = list(step.outputs)
    return data
