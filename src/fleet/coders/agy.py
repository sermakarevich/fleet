import json
from datetime import UTC, datetime
from pathlib import Path

from fleet.coders.base import Coder, render_prompt
from fleet.core.launch import LaunchPlan
from fleet.core.task import Event, Task


class AgyCoder(Coder):
    name = "agy"
    context_limit = 128_000
    default_model = "GPT-OSS 120B"
    # TODO(fleet-ml2s9): hand the fleet MCP servers
    # (integrations.mcp_servers.fleet_mcp_servers: ask_human, web_fetch) to
    # agy workers explicitly, the way claude (--mcp-config), codex
    # (CODEX_HOME) and opencode (OPENCODE_CONFIG_CONTENT) already do. The agy
    # CLI's MCP config mechanism is still unknown — check `agy --help` on a
    # machine with it installed, then mirror the per-coder adaptation here.

    def __init__(self, model: str = "GPT-OSS 120B") -> None:
        # NOTE: the `agy` CLI binary does not accept a model flag; it reads
        # its active model from `~/.gemini/antigravity-cli/settings.json`.
        # `self.model` is kept for supervisor logging and as a hook for a
        # future write-settings step.
        self.model = model

    def build_argv(self, task: Task, task_dir: Path, plan: LaunchPlan | None = None) -> list[str]:
        prompt = render_prompt(task, task_dir, plan)
        return [
            "agy",
            "-p",
            prompt,
            "--dangerously-skip-permissions",
        ]

    def env(self, task: Task, task_dir: Path) -> dict[str, str]:
        return {
            "FLEET_TASK_ID": task.id,
            "FLEET_TASK_DIR": str(task_dir),
        }

    def normalize_event(self, raw_line: str) -> Event | None:  # noqa: PLR0911  # ADR 0006 bead 7
        if not raw_line.strip():
            return None

        # Check if the line is JSON in case agy or its plugins ever output JSON.
        try:
            data = json.loads(raw_line)
            if isinstance(data, dict):
                t = data.get("type", "")
                ts = datetime.now(tz=UTC)
                if t == "assistant":
                    return Event(
                        kind="assistant_text",
                        raw=data,
                        ts=ts,
                        session_id=data.get("session_id"),
                        usage=data.get("message", {}).get("usage"),
                    )
                if t == "tool_use":
                    return Event(
                        kind="tool_use",
                        raw=data,
                        ts=ts,
                        tool_name=data.get("name"),
                    )
                if t == "tool_result":
                    return Event(
                        kind="tool_result",
                        raw=data,
                        ts=ts,
                        tool_name=data.get("name"),
                    )
                if t == "result":
                    return Event(
                        kind="session_ended",
                        raw=data,
                        ts=ts,
                        session_id=data.get("session_id"),
                        usage=data.get("usage"),
                    )
                return Event(
                    kind="assistant_text",
                    raw=data,
                    ts=ts,
                )
        except (json.JSONDecodeError, ValueError):
            pass

        # Since agy outputs raw text/markdown, parse non-empty lines as assistant_text
        # to allow live streaming/logging of the coder output in the fleet log files.
        return Event(
            kind="assistant_text",
            raw={"text": raw_line},
            ts=datetime.now(tz=UTC),
        )
