import json
from datetime import datetime, timezone
from pathlib import Path

from fleet.coder import Coder
from fleet.schemas import Event, Task

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
_INSTRUCTION_PATH = _TEMPLATES_DIR / "INSTRUCTION.md"
_HEADER_PATH = _TEMPLATES_DIR / "coder_header.md.tmpl"


class AgyCoder(Coder):
    name = "agy"
    context_limit = 128_000

    def __init__(self, model: str = "GPT-OSS 120B") -> None:
        # NOTE: the `agy` CLI binary does not accept a model flag; it reads
        # its active model from `~/.gemini/antigravity-cli/settings.json`.
        # `self.model` is kept for supervisor logging and as a hook for a
        # future write-settings step.
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
            "FLEET_ARTIFACT_DIR": str(task_dir / "artifacts"),
        }

    def normalize_event(self, raw_line: str) -> Event | None:
        if not raw_line.strip():
            return None

        # Check if the line is JSON in case agy or its plugins ever output JSON.
        try:
            data = json.loads(raw_line)
            if isinstance(data, dict):
                t = data.get("type", "")
                ts = datetime.now(tz=timezone.utc)
                if t == "assistant":
                    return Event(
                        kind="assistant_text",
                        raw=data,
                        ts=ts,
                        session_id=data.get("session_id"),
                        usage=data.get("message", {}).get("usage"),
                    )
                elif t == "tool_use":
                    return Event(
                        kind="tool_use",
                        raw=data,
                        ts=ts,
                        tool_name=data.get("name"),
                    )
                elif t == "tool_result":
                    return Event(
                        kind="tool_result",
                        raw=data,
                        ts=ts,
                        tool_name=data.get("name"),
                    )
                elif t == "result":
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
            ts=datetime.now(tz=timezone.utc),
        )
