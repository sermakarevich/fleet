import json
from datetime import UTC, datetime
from pathlib import Path

from fleet.coders.base import Coder, render_prompt
from fleet.core.launch import LaunchPlan
from fleet.core.task import Event, Task

_TOOL_ITEM_TYPES = frozenset({
    "command_execution",
    "file_change",
    "mcp_tool_call",
    "web_search",
    "collab_tool_call",
})


class CodexCoder(Coder):
    name = "codex"
    context_limit = 128_000
    default_model = "o4-mini"

    def __init__(self, model: str = "o4-mini") -> None:
        self.model = model

    def build_argv(
        self, task: Task, task_dir: Path, plan: LaunchPlan | None = None
    ) -> list[str]:
        prompt = render_prompt(task, task_dir, plan)
        argv = [
            "codex",
            "exec",
            "--json",
            "--dangerously-bypass-approvals-and-sandbox",
            "--model", self.model,
        ]
        if task.cwd:
            argv += ["--cd", task.cwd]
        argv.append(prompt)
        return argv

    def env(self, task: Task, task_dir: Path) -> dict[str, str]:
        return {
            "FLEET_TASK_ID": task.id,
            "FLEET_TASK_DIR": str(task_dir),
            "FLEET_ARTIFACT_DIR": str(task_dir / "artifacts"),
        }

    def normalize_event(self, raw_line: str) -> Event | None:  # noqa: PLR0911
        if not raw_line.strip():
            return None

        try:
            data = json.loads(raw_line)
        except (json.JSONDecodeError, ValueError):
            return None

        if not isinstance(data, dict):
            return None

        ts = datetime.now(tz=UTC)
        t = data.get("type", "")

        if t == "thread.started":
            return Event(
                kind="session_started",
                raw=data,
                ts=ts,
                session_id=data.get("thread_id"),
            )

        if t == "turn.completed":
            return Event(
                kind="session_ended",
                raw=data,
                ts=ts,
                usage=data.get("usage"),
            )

        if t in ("turn.failed", "error"):
            return Event(kind="error", raw=data, ts=ts)

        if t in ("item.started", "item.updated", "item.completed"):
            item = data.get("item", {})
            item_type = item.get("type", "")

            if item_type == "agent_message" and t == "item.completed":
                return Event(kind="assistant_text", raw=data, ts=ts)

            if item_type == "reasoning" and t == "item.completed":
                return Event(kind="thinking", raw=data, ts=ts)

            if item_type in _TOOL_ITEM_TYPES:
                if t == "item.started":
                    return Event(
                        kind="tool_use",
                        raw=data,
                        ts=ts,
                        tool_name=item_type,
                    )
                if t == "item.completed":
                    return Event(
                        kind="tool_result",
                        raw=data,
                        ts=ts,
                        tool_name=item_type,
                    )

        return None
