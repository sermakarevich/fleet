import json
import stat
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from http import HTTPStatus
from pathlib import Path
from typing import ClassVar

from fleet.coders.base import CoderSpec, lookup_handler, prompt_context
from fleet.coders.env import fleet_env
from fleet.coders.mcp import write_mcp_config
from fleet.core.launch import LaunchPlan
from fleet.core.task import Event, EventKind, Task
from fleet.integrations.mcp_servers import fleet_mcp_servers
from fleet.prompts import render
from fleet.state import paths as state_paths
from fleet.state.attempts import latest_attempt_dir

SHIPPED_HOOKS_DIR = Path(__file__).parent / "hooks"
"""Bash hooks shipped with fleet, installed into the project by this coder."""


def _extract_usage_pct(info: dict) -> float | None:
    """Return rate-limit usage on the 0-100 percent scale, or None.

    Claude CLI's `rate_limit_event` reports usage via `utilization`, a
    fraction in [0, 1] (can exceed 1.0 during overage). Older / fake
    payloads use `usage_pct` or `usagePct` already on the 0-100 scale.
    """
    pct = info.get("usage_pct")
    if pct is None:
        pct = info.get("usagePct")
    if pct is not None:
        return float(pct)
    util = info.get("utilization")
    if util is not None:
        return float(util) * 100.0
    return None


def _hard_rate_limit(data: dict) -> Event | None:
    """Hard rate-limit rejection: HTTP 429 or an explicit reject envelope.

    These markers ride outside the typed stream (the 429 fixture has no
    ``type`` key at all), so they are checked before the EVENT_MAP lookup.
    """
    if data.get("api_error_status") == HTTPStatus.TOO_MANY_REQUESTS or (
        data.get("error") == "rate_limit"
    ):
        return Event(
            kind=EventKind.RATE_LIMIT,
            raw=data,
            ts=datetime.now(tz=UTC),
            rate_info={
                "usage_pct": None,
                "resets_at": data.get("resetsAt"),
                "status": "rejected",
            },
        )
    return None


def _rate_limit_info(data: dict) -> Event | None:
    """Soft rate-limit warning (periodic usage envelope).

    Claude CLI emits one event per rateLimitType (five_hour, weekly,
    overage, …). Only the session-cap (five_hour) bound should gate
    the supervisor's spawn loop; longer-horizon budgets (weekly,
    overage) reset days from now and would freeze claims if mirrored
    into the gauge.
    """
    info = data.get("rate_limit_info", {})
    if not isinstance(info, dict) or info.get("rateLimitType") != "five_hour":
        return None
    return Event(
        kind=EventKind.RATE_LIMIT_INFO,
        raw=data,
        ts=datetime.now(tz=UTC),
        rate_info={
            "usage_pct": _extract_usage_pct(info),
            "resets_at": info.get("resetsAt"),
            "status": info.get("status"),
        },
    )


def _session_started(data: dict) -> Event | None:
    """Session start (system init)."""
    return Event(
        kind=EventKind.SESSION_STARTED,
        raw=data,
        ts=datetime.now(tz=UTC),
        session_id=data.get("session_id"),
    )


def _system_error(data: dict) -> Event | None:
    """System error."""
    return Event(kind=EventKind.ERROR, raw=data, ts=datetime.now(tz=UTC))


def _assistant(data: dict) -> Event | None:
    """Assistant message: thinking blocks first, then tool_use blocks, else text.

    Tool invocations arrive as content blocks inside assistant messages,
    never as top-level stream-json events. raw is the block itself so
    readers find the tool input at raw["input"] (files tab, stats).
    """
    msg = data.get("message", {})
    content = msg.get("content", []) if isinstance(msg, dict) else []
    usage = msg.get("usage") if isinstance(msg, dict) else None
    session_id = data.get("session_id")
    # Thinking blocks come first in extended-thinking responses.
    for block in content:
        if isinstance(block, dict) and block.get("type") == "thinking":
            return Event(
                kind=EventKind.THINKING,
                raw=data,
                ts=datetime.now(tz=UTC),
                session_id=session_id,
                usage=usage,
            )
    for block in content:
        if isinstance(block, dict) and block.get("type") == "tool_use":
            return Event(
                kind=EventKind.TOOL_USE,
                raw=block,
                ts=datetime.now(tz=UTC),
                session_id=session_id,
                tool_name=block.get("name"),
                usage=usage,
            )
    return Event(
        kind=EventKind.ASSISTANT_TEXT,
        raw=data,
        ts=datetime.now(tz=UTC),
        session_id=session_id,
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
    """Terminal result envelope: the session ended."""
    return Event(
        kind=EventKind.SESSION_ENDED,
        raw=data,
        ts=datetime.now(tz=UTC),
        session_id=data.get("session_id"),
        usage=data.get("usage"),
    )


EVENT_MAP: dict[tuple[str, str | None], Callable[[dict], Event | None]] = {
    ("rate_limit_event", None): _rate_limit_info,
    ("system", "init"): _session_started,
    ("system", "error"): _system_error,
    ("assistant", None): _assistant,
    ("tool_use", None): _tool_use,
    ("tool_result", None): _tool_result,
    ("result", None): _session_ended,
}


def _attempt_dir_for(task_dir: Path) -> Path:
    """This task's Claude ``--mcp-config`` directory: the current attempt's dir.

    Falls back to the task directory itself (unit tests, ad-hoc runs). The
    file content is attempt-independent, so resolving "latest" here and in
    ``write_runtime_config`` always agrees within one attempt.
    """
    return latest_attempt_dir(task_dir) or task_dir


@dataclass(frozen=True)
class ClaudeCoder:
    """The claude CLI coder: stream-json argv, MCP config, project hooks."""

    spec: ClassVar[CoderSpec] = CoderSpec(
        name="claude", default_model="sonnet", context_limit=200_000
    )

    fleet_home: Path
    model: str = "sonnet"

    def build_argv(self, task: Task, task_dir: Path, plan: LaunchPlan | None = None) -> list[str]:
        mode, ctx = prompt_context(task, task_dir, plan)
        prompt = render(mode, ctx)
        # The worker prompt tells the model to call the ask_human MCP tool, so
        # the server must be handed explicitly: --mcp-config points at the
        # fleet-written mcp.json, --strict-mcp-config keeps the worker
        # environment deterministic (no inheritance of the operator's personal
        # ~/.claude.json servers). The file is (re)written here so argv always
        # points at a real file; write_runtime_config writes the same path
        # before spawn — both resolve via _attempt_dir_for, so they always
        # agree within one attempt. The write raises on OSError: the worker
        # turns it into a failed step instead of launching without ask_human.
        mcp_path = write_mcp_config(_attempt_dir_for(task_dir), fleet_mcp_servers(self.fleet_home))
        return [
            "claude",
            "-p",
            "--verbose",
            "--model",
            self.model,
            "--output-format",
            "stream-json",
            "--mcp-config",
            str(mcp_path),
            "--strict-mcp-config",
            # Headless workers have no human to answer a permission prompt. Without this,
            # settings' default permission mode decides each write per request and can refuse
            # ("Claude requested permissions to write to <file>, but you haven't granted it
            # yet"), which strands the task. agy takes the same flag for the same reason.
            "--dangerously-skip-permissions",
            prompt,
        ]

    def env(self, task: Task, task_dir: Path) -> dict[str, str]:
        return fleet_env(task, task_dir)

    def write_runtime_config(self, project: Path, task: Task) -> None:
        """Write fleet-managed .claude/settings.json and hook scripts into project root.

        Also writes this task's Claude ``--mcp-config`` file (ask_human +
        web_fetch, from ``integrations.mcp_servers``) into the current attempt
        directory. The task directory is resolved best-effort from FLEET_HOME
        + task id — write_runtime_config only receives the project root, so a
        missing id (unit tests, ad-hoc runs) skips the mcp.json write; a real
        write failure raises so the worker fails the step instead of running
        without ask_human.
        """
        hooks_src = SHIPPED_HOOKS_DIR
        hooks_dst = project / ".fleet" / "hooks"
        hooks_dst.mkdir(parents=True, exist_ok=True)

        for name in ("precompact.sh", "pretool_askuserquestion.sh", "posttool_checkpoint.sh"):
            dest = hooks_dst / name
            dest.write_bytes((hooks_src / name).read_bytes())
            dest.chmod(dest.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

        claude_dir = project / ".claude"
        claude_dir.mkdir(parents=True, exist_ok=True)
        settings_path = claude_dir / "settings.json"

        existing: dict = {}
        if settings_path.exists():
            try:
                existing = json.loads(settings_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                existing = {}

        fleet_hook_entries: dict[str, dict] = {
            "PreCompact": {
                "_fleet_managed": True,
                "matcher": "",
                "hooks": [{"type": "command", "command": ".fleet/hooks/precompact.sh"}],
            },
            "PreToolUse": {
                "_fleet_managed": True,
                "matcher": "AskUserQuestion",
                "hooks": [
                    {
                        "type": "command",
                        "command": ".fleet/hooks/pretool_askuserquestion.sh",
                    }
                ],
            },
            "PostToolUse": {
                "_fleet_managed": True,
                "matcher": "",
                "hooks": [
                    {
                        "type": "command",
                        "command": ".fleet/hooks/posttool_checkpoint.sh",
                    }
                ],
            },
        }

        hooks: dict = dict(existing.get("hooks", {}))
        for event_type, fleet_entry in fleet_hook_entries.items():
            non_fleet = [e for e in hooks.get(event_type, []) if not e.get("_fleet_managed")]
            hooks[event_type] = non_fleet + [fleet_entry]

        result = {**existing, "hooks": hooks}
        settings_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

        task_id = getattr(task, "id", None)
        if task_id:
            task_dir = state_paths.task_dir(self.fleet_home, task_id)
            write_mcp_config(_attempt_dir_for(task_dir), fleet_mcp_servers(self.fleet_home))

    def normalize_event(self, raw_line: str) -> Event | None:
        """Parse one stdout line: hard-reject check, then EVENT_MAP on (type, subtype)."""
        try:
            data = json.loads(raw_line)
        except (json.JSONDecodeError, ValueError):
            return None
        if not isinstance(data, dict):
            return None
        rejected = _hard_rate_limit(data)
        if rejected is not None:
            return rejected
        handler = lookup_handler(EVENT_MAP, (data.get("type", ""), data.get("subtype")))
        if handler is None:
            return None
        return handler(data)
