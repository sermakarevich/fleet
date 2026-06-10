import json
from datetime import datetime, timezone
from pathlib import Path

from fleet.coders.base import Coder
from fleet.schemas import Event, Task

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
_INSTRUCTION_PATH = _TEMPLATES_DIR / "INSTRUCTION.md"
_HEADER_PATH = _TEMPLATES_DIR / "coder_header.md.tmpl"

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

    def build_argv(self, task: Task, task_dir: Path) -> list[str]:
        artifacts_dir = task_dir / "artifacts"
        instructions = _INSTRUCTION_PATH.read_text(encoding="utf-8").strip()
        invocation_line = f"Invocation directory: {task.cwd}" if task.cwd else ""
        header = _HEADER_PATH.read_text(encoding="utf-8").format(
            task_id=task.id,
            task_title=task.title,
            task_description=task.description or "",
            task_dir=task_dir,
            artifacts_dir=artifacts_dir,
            invocation_line=invocation_line,
        ).strip()
        prompt = f"{header}\n\n---\n\n{instructions}"
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

        ts = datetime.now(tz=timezone.utc)
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
