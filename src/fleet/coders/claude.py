import json
import stat
from datetime import UTC, datetime
from pathlib import Path

from fleet.coders.base import Coder, render_prompt
from fleet.core.launch import LaunchPlan
from fleet.core.task import Event, Task


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


MCP_CONFIG_FILENAME = "mcp.json"


def _mcp_config_path(task_dir: Path) -> Path:
    """Where this task's Claude ``--mcp-config`` file lives.

    The current attempt's directory when one is recorded, else the task
    directory itself (unit tests, ad-hoc runs). The file content is
    attempt-independent, so resolving "latest" here and in
    ``write_runtime_config`` always agrees within one attempt.
    """
    from fleet.state.attempts import latest_attempt_dir

    attempt_dir = latest_attempt_dir(task_dir)
    return (attempt_dir or task_dir) / MCP_CONFIG_FILENAME


def _write_mcp_config(path: Path, home: Path) -> Path:
    """Write Claude's ``--mcp-config`` JSON (``{"mcpServers": ...}``) to *path*.

    Server definitions come from ``integrations.mcp_servers.fleet_mcp_servers``
    (the same source opencode and codex use); *home* is FLEET_HOME. Values are
    paths and module names, never secrets.
    """
    from fleet.integrations.mcp_servers import fleet_mcp_servers

    servers = {}
    for name, entry in fleet_mcp_servers(home).items():
        servers[name] = {
            "command": entry["command"],
            "args": list(entry["args"]),
            "env": dict(entry["env"]),
        }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"mcpServers": servers}, indent=2) + "\n", encoding="utf-8")
    return path


class ClaudeCoder(Coder):
    name = "claude"
    context_limit = 200_000
    default_model = "sonnet"

    def __init__(self, model: str = "sonnet") -> None:
        self.model = model

    def build_argv(
        self, task: Task, task_dir: Path, plan: LaunchPlan | None = None
    ) -> list[str]:
        prompt = render_prompt(task, task_dir, plan)
        # The worker prompt tells the model to call the ask_human MCP tool, so
        # the server must be handed explicitly: --mcp-config points at the
        # fleet-written mcp.json, --strict-mcp-config keeps the worker
        # environment deterministic (no inheritance of the operator's personal
        # ~/.claude.json servers). The file is (re)written best-effort here so
        # argv always points at a real file; write_runtime_config writes the
        # same path before spawn — both resolve via _mcp_config_path, so they
        # always agree within one attempt.
        from fleet.state.paths import fleet_home

        mcp_path = _mcp_config_path(task_dir)
        try:
            _write_mcp_config(mcp_path, fleet_home())
        except OSError:
            pass
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
        return {
            "FLEET_TASK_ID": task.id,
            "FLEET_TASK_DIR": str(task_dir),
        }

    @staticmethod
    def _shipped_hooks_dir() -> Path:
        return Path(__file__).parent / "hooks"

    def write_runtime_config(self, project: Path, task: object) -> None:
        """Write fleet-managed .claude/settings.json and hook scripts into project root.

        Also writes this task's Claude ``--mcp-config`` file (ask_human +
        web_fetch, from ``integrations.mcp_servers``) into the current attempt
        directory. The task directory is resolved best-effort from FLEET_HOME
        + task id — write_runtime_config only receives the project root, so a
        failure to resolve (unit tests, ad-hoc runs) skips the mcp.json write
        instead of crashing; build_argv re-resolves from its task_dir and
        writes the same path, so the two always agree within one attempt.
        """
        hooks_src = self._shipped_hooks_dir()
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
            non_fleet = [
                e for e in hooks.get(event_type, []) if not e.get("_fleet_managed")
            ]
            hooks[event_type] = non_fleet + [fleet_entry]

        result = {**existing, "hooks": hooks}
        settings_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

        try:
            from fleet.state.paths import fleet_home
            from fleet.state.paths import task_dir as _resolve_task_dir

            task_id = getattr(task, "id", None)
            if task_id:
                tdir = _resolve_task_dir(fleet_home(), task_id)
                _write_mcp_config(_mcp_config_path(tdir), fleet_home())
        except OSError:
            pass

    def normalize_event(self, raw_line: str) -> Event | None:  # noqa: PLR0911
        try:
            data = json.loads(raw_line)
        except (json.JSONDecodeError, ValueError):
            return None

        if not isinstance(data, dict):
            return None

        ts = datetime.now(tz=UTC)
        t = data.get("type", "")

        # Soft rate-limit warning (periodic usage envelope)
        if t == "rate_limit_event":
            info = data.get("rate_limit_info", {})
            # Claude CLI emits one event per rateLimitType (five_hour, weekly,
            # overage, …). Only the session-cap (five_hour) bound should gate
            # the supervisor's spawn loop; longer-horizon budgets (weekly,
            # overage) reset days from now and would freeze claims if mirrored
            # into the gauge.
            if info.get("rateLimitType") != "five_hour":
                return None
            return Event(
                kind="rate_limit_info",
                raw=data,
                ts=ts,
                rate_info={
                    "usage_pct": _extract_usage_pct(info),
                    "resets_at": info.get("resetsAt"),
                    "status": info.get("status"),
                },
            )

        # Hard rate-limit rejection (HTTP 429 or explicit reject envelope)
        if data.get("api_error_status") == 429 or data.get("error") == "rate_limit":
            return Event(
                kind="rate_limit",
                raw=data,
                ts=ts,
                rate_info={
                    "usage_pct": None,
                    "resets_at": data.get("resetsAt"),
                    "status": "rejected",
                },
            )

        # Session start (system init)
        if t == "system" and data.get("subtype") == "init":
            return Event(
                kind="session_started",
                raw=data,
                ts=ts,
                session_id=data.get("session_id"),
            )

        # System error
        if t == "system" and data.get("subtype") == "error":
            return Event(kind="error", raw=data, ts=ts)

        # Assistant message — may be text or thinking
        if t == "assistant":
            msg = data.get("message", {})
            content = msg.get("content", [])
            usage = msg.get("usage")
            session_id = data.get("session_id")
            # Thinking blocks come first in extended-thinking responses
            for block in content:
                if isinstance(block, dict) and block.get("type") == "thinking":
                    return Event(
                        kind="thinking",
                        raw=data,
                        ts=ts,
                        session_id=session_id,
                        usage=usage,
                    )
            # Tool invocations arrive as content blocks inside assistant messages,
            # never as top-level stream-json events. raw is the block itself so
            # readers find the tool input at raw["input"] (files tab, stats).
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    return Event(
                        kind="tool_use",
                        raw=block,
                        ts=ts,
                        session_id=session_id,
                        tool_name=block.get("name"),
                        usage=usage,
                    )
            return Event(
                kind="assistant_text",
                raw=data,
                ts=ts,
                session_id=session_id,
                usage=usage,
            )

        # Tool invocation
        if t == "tool_use":
            return Event(
                kind="tool_use",
                raw=data,
                ts=ts,
                tool_name=data.get("name"),
            )

        # Tool result
        if t == "tool_result":
            return Event(
                kind="tool_result",
                raw=data,
                ts=ts,
                tool_name=data.get("name"),
            )

        # Terminal result envelope — session ended
        if t == "result":
            return Event(
                kind="session_ended",
                raw=data,
                ts=ts,
                session_id=data.get("session_id"),
                usage=data.get("usage"),
            )

        return None
