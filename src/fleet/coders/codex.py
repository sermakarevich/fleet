"""The codex coder: `codex exec --json` sessions.

MCP wiring: codex reads MCP servers from ``~/.codex/config.toml``. To keep
workers isolated (never touching the operator's personal config) fleet writes
a per-attempt ``CODEX_HOME`` directory holding a ``config.toml`` with the
fleet servers (``integrations.mcp_servers.fleet_mcp_servers``) and points the
worker at it via the ``CODEX_HOME`` env var. This file-based route was chosen
over ``-c mcp_servers.*`` CLI overrides because the codex binary is not
installed in every fleet environment (``codex --help`` cannot be checked
here), so a ``-c`` incantation could not be verified; if ``-c`` TOML
overrides are confirmed on the installed CLI later, build_argv is the place
to layer them on top. Values written are paths and module names, never
secrets.
"""

import json
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar

from fleet.coders.base import CoderSpec, Workspace, lookup_handler, prompt_context
from fleet.coders.env import fleet_env
from fleet.core.launch import LaunchPlan
from fleet.core.task import Event, Task
from fleet.integrations.mcp_servers import fleet_mcp_servers
from fleet.prompts import render
from fleet.state.attempts import latest_attempt_dir
from fleet.state.paths import task_dir as _resolve_task_dir

_TOOL_ITEM_TYPES = frozenset(
    {
        "command_execution",
        "file_change",
        "mcp_tool_call",
        "web_search",
        "collab_tool_call",
    }
)

CODEX_HOME_DIRNAME = "codex_home"
CODEX_CONFIG_FILENAME = "config.toml"


def _toml_str(value: str) -> str:
    """Quote *value* as a TOML basic string (JSON quoting is compatible)."""
    return json.dumps(value)


def _codex_home_path(task_dir: Path) -> Path:
    """Per-attempt CODEX_HOME: the current attempt's dir when one is recorded,
    else the task dir itself (unit tests, ad-hoc runs)."""

    attempt_dir = latest_attempt_dir(task_dir)
    return (attempt_dir or task_dir) / CODEX_HOME_DIRNAME


def _render_codex_config(home: Path) -> str:
    """Render a codex ``config.toml`` with the fleet MCP servers.

    *home* is FLEET_HOME. One ``[mcp_servers.<name>]`` table per server from
    ``integrations.mcp_servers.fleet_mcp_servers``.
    """

    lines = [
        "# Fleet-managed codex config: MCP servers every worker must have.",
        "# Regenerated before each spawn; do not edit by hand.",
        "",
    ]
    for name, entry in fleet_mcp_servers(home).items():
        args = ", ".join(_toml_str(a) for a in entry["args"])
        lines.append(f"[mcp_servers.{name}]")
        lines.append(f"command = {_toml_str(entry['command'])}")
        lines.append(f"args = [{args}]")
        if entry["env"]:
            env_pairs = ", ".join(
                f"{_toml_str(k)} = {_toml_str(v)}" for k, v in sorted(entry["env"].items())
            )
            lines.append(f"env = {{ {env_pairs} }}")
        lines.append("")
    return "\n".join(lines)


def _write_codex_config(codex_home: Path, home: Path) -> Path:
    """Write ``config.toml`` into *codex_home* and return its path."""
    codex_home.mkdir(parents=True, exist_ok=True)
    path = codex_home / CODEX_CONFIG_FILENAME
    path.write_text(_render_codex_config(home), encoding="utf-8")
    return path


def _session_started(data: dict) -> Event | None:
    """A thread started."""
    return Event(
        kind="session_started",
        raw=data,
        ts=datetime.now(tz=UTC),
        session_id=data.get("thread_id"),
    )


def _session_ended(data: dict) -> Event | None:
    """A turn completed."""
    return Event(
        kind="session_ended",
        raw=data,
        ts=datetime.now(tz=UTC),
        usage=data.get("usage"),
    )


def _error(data: dict) -> Event | None:
    """A failed turn or error envelope."""
    return Event(kind="error", raw=data, ts=datetime.now(tz=UTC))


def _assistant_text(data: dict) -> Event | None:
    """A completed agent message."""
    return Event(kind="assistant_text", raw=data, ts=datetime.now(tz=UTC))


def _thinking(data: dict) -> Event | None:
    """A completed reasoning block."""
    return Event(kind="thinking", raw=data, ts=datetime.now(tz=UTC))


def _tool_use(data: dict) -> Event | None:
    """A tool item started; the tool name is the item type."""
    item = data.get("item", {})
    tool_name = item.get("type") if isinstance(item, dict) else None
    return Event(
        kind="tool_use",
        raw=data,
        ts=datetime.now(tz=UTC),
        tool_name=tool_name,
    )


def _tool_result(data: dict) -> Event | None:
    """A tool item completed; the tool name is the item type."""
    item = data.get("item", {})
    tool_name = item.get("type") if isinstance(item, dict) else None
    return Event(
        kind="tool_result",
        raw=data,
        ts=datetime.now(tz=UTC),
        tool_name=tool_name,
    )


EVENT_MAP: dict[tuple[str, str | None], Callable[[dict], Event | None]] = {
    ("thread.started", None): _session_started,
    ("turn.completed", None): _session_ended,
    ("turn.failed", None): _error,
    ("error", None): _error,
    ("item.completed", "agent_message"): _assistant_text,
    ("item.completed", "reasoning"): _thinking,
    **{("item.started", tool): _tool_use for tool in _TOOL_ITEM_TYPES},
    **{("item.completed", tool): _tool_result for tool in _TOOL_ITEM_TYPES},
}


def _event_key(data: dict) -> tuple[str, str | None]:
    """Lookup key for EVENT_MAP: item events dispatch on the item type."""
    event_type = data.get("type", "")
    if isinstance(event_type, str) and event_type.startswith("item."):
        item = data.get("item", {})
        subtype = item.get("type") if isinstance(item, dict) else None
        return (event_type, subtype)
    return (event_type, data.get("subtype"))


@dataclass(frozen=True)
class CodexCoder:
    """The codex CLI coder: per-attempt CODEX_HOME, workdir via --cd."""

    spec: ClassVar[CoderSpec] = CoderSpec(
        name="codex", default_model="o4-mini", context_limit=128_000
    )

    fleet_home: Path
    model: str = "o4-mini"

    def build_argv(self, task: Task, task_dir: Path, plan: LaunchPlan | None = None) -> list[str]:
        mode, ctx = prompt_context(task, task_dir, plan)
        prompt = render(mode, ctx)
        argv = [
            "codex",
            "exec",
            "--json",
            "--dangerously-bypass-approvals-and-sandbox",
            "--model",
            self.model,
        ]
        workdir = Workspace(task_dir=task_dir, cwd=task.cwd).workdir
        if workdir:
            argv += ["--cd", workdir]
        argv.append(prompt)
        return argv

    def env(self, task: Task, task_dir: Path) -> dict[str, str]:
        return {
            **fleet_env(task, task_dir),
            # Isolate the worker from the operator's ~/.codex/config.toml:
            # codex resolves its config under $CODEX_HOME.
            "CODEX_HOME": str(_codex_home_path(task_dir)),
        }

    def write_runtime_config(self, project: Path, task: Task) -> None:
        """Write the per-attempt CODEX_HOME/config.toml (fleet MCP servers).

        The task directory is resolved best-effort from FLEET_HOME + task id
        (this hook only receives the project root); resolution failures skip
        the write instead of crashing. env() points at the same path, so the
        two agree within one attempt.
        """
        with suppress(OSError):
            _write_codex_config(
                _codex_home_path(_resolve_task_dir(self.fleet_home, task.id)), self.fleet_home
            )

    def normalize_event(self, raw_line: str) -> Event | None:
        """Parse one stdout line via EVENT_MAP keyed on (type, item type)."""
        if not raw_line.strip():
            return None
        try:
            data = json.loads(raw_line)
        except (json.JSONDecodeError, ValueError):
            return None
        if not isinstance(data, dict):
            return None
        handler = lookup_handler(EVENT_MAP, _event_key(data))
        if handler is None:
            return None
        return handler(data)
