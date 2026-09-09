import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar

from fleet.coders.base import CoderSpec, lookup_handler, prompt_context
from fleet.coders.env import fleet_env
from fleet.core.launch import LaunchPlan
from fleet.core.task import Event, EventKind, Task
from fleet.prompts import render


def _assistant_text(data: dict) -> Event | None:
    """An assistant payload."""
    message = data.get("message")
    usage = message.get("usage") if isinstance(message, dict) else None
    return Event(
        kind=EventKind.ASSISTANT_TEXT,
        raw=data,
        ts=datetime.now(tz=UTC),
        session_id=data.get("session_id"),
        usage=usage,
    )


def _tool_use(data: dict) -> Event | None:
    """A tool invocation."""
    return Event(
        kind=EventKind.TOOL_USE,
        raw=data,
        ts=datetime.now(tz=UTC),
        tool_name=data.get("name"),
    )


def _tool_result(data: dict) -> Event | None:
    """A tool result."""
    return Event(
        kind=EventKind.TOOL_RESULT,
        raw=data,
        ts=datetime.now(tz=UTC),
        tool_name=data.get("name"),
    )


def _session_ended(data: dict) -> Event | None:
    """A terminal result envelope."""
    return Event(
        kind=EventKind.SESSION_ENDED,
        raw=data,
        ts=datetime.now(tz=UTC),
        session_id=data.get("session_id"),
        usage=data.get("usage"),
    )


EVENT_MAP: dict[tuple[str, str | None], Callable[[dict], Event | None]] = {
    ("assistant", None): _assistant_text,
    ("tool_use", None): _tool_use,
    ("tool_result", None): _tool_result,
    ("result", None): _session_ended,
}


def _raw_text_event(raw_line: str) -> Event:
    """A non-JSON stdout line: agy emits raw text/markdown, streamed live."""
    return Event(
        kind=EventKind.ASSISTANT_TEXT,
        raw={"text": raw_line},
        ts=datetime.now(tz=UTC),
    )


@dataclass(frozen=True)
class AgyCoder:
    """The agy CLI coder: prompt-only argv, raw-text event stream.

    ``fleet_home`` is reserved for the fleet MCP wiring (see the TODO below);
    it is unused today but kept so every coder builds the same way.
    """

    spec: ClassVar[CoderSpec] = CoderSpec(
        name="agy", default_model="GPT-OSS 120B", context_limit=128_000
    )

    fleet_home: Path
    # NOTE: the `agy` CLI binary does not accept a model flag; it reads its
    # active model from `~/.gemini/antigravity-cli/settings.json`. `model` is
    # kept for supervisor logging and as a hook for a future write-settings step.
    model: str = "GPT-OSS 120B"
    # TODO(fleet-ml2s9): hand the fleet MCP servers
    # (integrations.mcp_servers.fleet_mcp_servers: ask_human, web_fetch) to
    # agy workers explicitly, the way claude (--mcp-config), codex
    # (CODEX_HOME) and opencode (OPENCODE_CONFIG_CONTENT) already do. The agy
    # CLI's MCP config mechanism is still unknown — check `agy --help` on a
    # machine with it installed, then mirror the per-coder adaptation here.

    def build_argv(self, task: Task, task_dir: Path, plan: LaunchPlan | None = None) -> list[str]:
        mode, ctx = prompt_context(task, task_dir, plan)
        prompt = render(mode, ctx)
        return [
            "agy",
            "-p",
            prompt,
            "--dangerously-skip-permissions",
        ]

    def env(self, task: Task, task_dir: Path) -> dict[str, str]:
        return fleet_env(task, task_dir)

    def normalize_event(self, raw_line: str) -> Event | None:
        """Parse one stdout line via EVENT_MAP; raw text streams as assistant_text.

        Unknown JSON objects fall back to assistant_text (agy has no typed
        envelope for them); only blank lines return None.
        """
        if not raw_line.strip():
            return None
        try:
            data = json.loads(raw_line)
        except (json.JSONDecodeError, ValueError):
            return _raw_text_event(raw_line)
        if not isinstance(data, dict):
            return _raw_text_event(raw_line)
        handler = lookup_handler(EVENT_MAP, (data.get("type", ""), data.get("subtype")))
        if handler is None:
            return Event(kind=EventKind.ASSISTANT_TEXT, raw=data, ts=datetime.now(tz=UTC))
        return handler(data)
