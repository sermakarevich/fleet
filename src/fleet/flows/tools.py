"""Declared executables coders and starts can use (DESIGN.md §3.7).

A tool is one YAML file in a ``tools/`` folder: a ``command`` argv list whose
elements may contain ``{{ args.x }}`` templates, a declared ``args`` mapping,
required ``env`` variable names, and an ``output`` kind (``json`` | ``lines``
| ``text``). Tools become ``kind: tool`` steps, ``on: tool`` starts, or a
"Tools" section appended to a coder prompt. This module holds the frozen
model and validation; running a tool step lives in ``pool/tool_run.py``.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from fleet.core.errors import FlowInvalid
from fleet.flows.templates import render

TOOL_VERSION = 2
OUTPUT_KINDS: tuple[str, ...] = ("json", "lines", "text")

_NAME_RE = re.compile(r"[a-z][a-z0-9_-]*\Z")

_KNOWN_FIELDS = frozenset(
    {"fleet_tool", "description", "command", "args", "env", "output", "timeout"}
)
_KNOWN_ARG_FIELDS = frozenset({"description", "required", "default"})


@dataclass(frozen=True)
class ToolArg:
    """One declared tool argument with its requirement rule."""

    name: str
    description: str = ""
    required: bool = False
    default: str | None = None


@dataclass(frozen=True)
class Tool:
    """A declared executable: argv template plus arg/env/output policy."""

    name: str
    description: str = ""
    command: tuple[str, ...] = ()
    args: tuple[ToolArg, ...] = ()
    env: tuple[str, ...] = ()
    output: str = "text"
    timeout: int = 120
    source: str = ""


def _valid_name(value: str) -> bool:
    """Return True when ``value`` matches ``[a-z][a-z0-9_-]*`` fully."""
    return bool(_NAME_RE.match(value))


def _command_parts(raw_command: Any) -> tuple[list[str], list[str]]:
    """Split raw ``command`` into (elements, problems)."""
    if (
        not isinstance(raw_command, (list, tuple))
        or len(raw_command) == 0
        or any(not isinstance(item, str) for item in raw_command)
    ):
        return [], ["command: must be a non-empty list of strings"]
    return list(raw_command), []


def _env_parts(raw_env: Any) -> tuple[list[str], list[str]]:
    """Split raw ``env`` into (names, problems)."""
    if not isinstance(raw_env, (list, tuple)) or any(not isinstance(item, str) for item in raw_env):
        return [], ["env: must be a list of strings"]
    return list(raw_env), []


def _output_parts(raw_output: Any) -> tuple[str, list[str]]:
    """Split raw ``output`` into (kind, problems)."""
    if raw_output not in OUTPUT_KINDS:
        return "text", ["output: must be one of json, lines, text"]
    return raw_output, []


def _timeout_parts(raw_timeout: Any) -> tuple[int, list[str]]:
    """Split raw ``timeout`` into (seconds, problems)."""
    if not isinstance(raw_timeout, int) or isinstance(raw_timeout, bool) or raw_timeout <= 0:
        return 120, ["timeout: must be a positive integer"]
    return raw_timeout, []


def _checked_arg(arg_name: Any, raw_arg: Any) -> tuple[ToolArg | None, list[str]]:
    """Validate one arg entry into (ToolArg or None, problems)."""
    problems: list[str] = []
    if not isinstance(arg_name, str) or not _valid_name(arg_name):
        return None, [f"arg {arg_name}: must match [a-z][a-z0-9_-]*"]
    if not isinstance(raw_arg, Mapping):
        return None, [f"arg {arg_name}: must be a mapping"]
    for arg_key in raw_arg:
        if arg_key not in _KNOWN_ARG_FIELDS:
            problems.append(f"arg {arg_name}: unknown field {arg_key}")
    arg_description = raw_arg.get("description", "")
    if not isinstance(arg_description, str):
        problems.append(f"arg {arg_name}: description must be a string")
        arg_description = ""
    required = raw_arg.get("required", False)
    if not isinstance(required, bool):
        problems.append(f"arg {arg_name}: required must be a boolean")
        required = False
    default = raw_arg.get("default", None)
    if default is not None and not isinstance(default, str):
        problems.append(f"arg {arg_name}: default must be a string")
        default = None
    if required and default is not None:
        problems.append(f"arg {arg_name}: default and required are exclusive")
    checked = ToolArg(
        name=arg_name, description=arg_description, required=required, default=default
    )
    return checked, problems


def _args_parts(raw_args: Any) -> tuple[list[ToolArg], list[str]]:
    """Split raw ``args`` into (declared args, problems)."""
    if not isinstance(raw_args, Mapping):
        return [], ["args: must be a mapping"]
    parsed: list[ToolArg] = []
    problems: list[str] = []
    for arg_name, raw_arg in raw_args.items():
        checked, arg_problems = _checked_arg(arg_name, raw_arg)
        problems.extend(arg_problems)
        if checked is not None:
            parsed.append(checked)
    return parsed, problems


def tool_from_dict(data: Mapping[str, Any], name: str, source: str = "") -> Tool:
    """Build a :class:`Tool` from parsed YAML, collecting every problem.

    ``data`` holds the YAML mapping (``fleet_tool``, ``description``,
    ``command``, ``args``, ``env``, ``output``, ``timeout``); ``name`` is the
    tool name from the file name and ``source`` the file path for provenance.
    Raises :class:`FlowInvalid` with all problems found.
    """
    problems: list[str] = []

    if not isinstance(name, str) or not _valid_name(name):
        problems.append("name: must match [a-z][a-z0-9_-]*")

    if not isinstance(data, Mapping):
        raise FlowInvalid(problems + ["tool: must be a mapping"])

    for key in data:
        if key not in _KNOWN_FIELDS:
            problems.append(f"unknown field {key}")

    if data.get("fleet_tool") != TOOL_VERSION:
        problems.append("fleet_tool: must be 2")

    description = data.get("description", "")
    if not isinstance(description, str):
        problems.append("description: must be a string")
        description = ""

    command, command_problems = _command_parts(data.get("command"))
    problems.extend(command_problems)
    parsed_args, args_problems = _args_parts(data.get("args", {}))
    problems.extend(args_problems)
    env, env_problems = _env_parts(data.get("env", []))
    problems.extend(env_problems)
    output, output_problems = _output_parts(data.get("output", "text"))
    problems.extend(output_problems)
    timeout, timeout_problems = _timeout_parts(data.get("timeout", 120))
    problems.extend(timeout_problems)

    if problems:
        raise FlowInvalid(problems)
    return Tool(
        name=name,
        description=description,
        command=tuple(command),
        args=tuple(parsed_args),
        env=tuple(env),
        output=output,
        timeout=timeout,
        source=source,
    )


def tool_to_dict(tool: Tool) -> dict[str, Any]:
    """Serialize ``tool`` back to the YAML-mapping shape ``tool_from_dict`` reads."""
    arg_map: dict[str, Any] = {}
    for arg in tool.args:
        entry: dict[str, Any] = {
            "description": arg.description,
            "required": arg.required,
        }
        if arg.default is not None:
            entry["default"] = arg.default
        arg_map[arg.name] = entry
    return {
        "fleet_tool": TOOL_VERSION,
        "description": tool.description,
        "command": list(tool.command),
        "args": arg_map,
        "env": list(tool.env),
        "output": tool.output,
        "timeout": tool.timeout,
    }


def missing_env(tool: Tool, environ: Mapping[str, str]) -> list[str]:
    """Return required env names that are unset or empty in ``environ``."""
    return [var_name for var_name in tool.env if not environ.get(var_name)]


def resolve_args(tool: Tool, given: Mapping[str, str]) -> dict[str, str]:
    """Fill ``given`` with declared defaults; reject missing required and unknown.

    Raises :class:`FlowInvalid` naming every missing required argument
    (``arg <name>: required``) and every undeclared one
    (``arg <name>: unknown``).
    """
    declared = {arg.name: arg for arg in tool.args}
    problems: list[str] = []
    resolved: dict[str, str] = {}
    for arg in tool.args:
        if arg.name in given:
            resolved[arg.name] = given[arg.name]
        elif arg.default is not None:
            resolved[arg.name] = arg.default
        elif arg.required:
            problems.append(f"arg {arg.name}: required")
    for given_name in given:
        if given_name not in declared:
            problems.append(f"arg {given_name}: unknown")
    if problems:
        raise FlowInvalid(problems)
    return resolved


def command_for(tool: Tool, given: Mapping[str, str]) -> list[str]:
    """Resolve ``given`` args and render each command element over them.

    Every argv element is rendered separately with ``{"args": resolved}``;
    an argument value containing spaces stays one element (no shell split).
    """
    resolved = resolve_args(tool, given)
    context: dict[str, Any] = {"args": resolved}
    return [render(element, context) for element in tool.command]


def parse_output(tool: Tool, stdout: str) -> Any:
    """Parse ``stdout`` according to the tool's declared output kind."""
    if tool.output == "json":
        try:
            return json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise FlowInvalid(f"output: not valid JSON: {exc}") from exc
    if tool.output == "lines":
        return [line.strip() for line in stdout.splitlines() if line.strip()]
    return stdout


def describe_for_prompt(tool: Tool) -> str:
    """Render a Markdown block describing ``tool`` for a coder prompt."""
    parts = [f"### {tool.name}", tool.description, "", f"Command: `{' '.join(tool.command)}`"]
    if tool.args:
        rendered_args = "; ".join(_describe_arg(arg) for arg in tool.args)
        parts.append(f"Args: {rendered_args}")
    else:
        parts.append("Args: none")
    return "\n".join(parts) + "\n"


def _describe_arg(arg: ToolArg) -> str:
    """Render one argument as ``name (required|optional[, default x]): description``."""
    status = "required" if arg.required else "optional"
    if arg.default is not None:
        status += f", default {arg.default}"
    return f"{arg.name} ({status}): {arg.description}"
