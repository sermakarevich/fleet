import json
from datetime import datetime, timezone
from pathlib import Path

from fleet.coder import Coder
from fleet.schemas import Event, Task


_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
_INSTRUCTION_PATH = _TEMPLATES_DIR / "INSTRUCTION.md"
_HEADER_PATH = _TEMPLATES_DIR / "coder_header.md.tmpl"


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


class ClaudeCoder(Coder):
    name = "claude"

    def __init__(self, model: str = "sonnet") -> None:
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
            "claude",
            "-p",
            "--verbose",
            "--model", self.model,
            "--output-format", "stream-json",
            prompt,
        ]

    def env(self, task: Task, task_dir: Path) -> dict[str, str]:
        return {
            "FLEET_TASK_ID": task.id,
            "FLEET_TASK_DIR": str(task_dir),
            "FLEET_ARTIFACT_DIR": str(task_dir / "artifacts"),
        }

    def normalize_event(self, raw_line: str) -> Event | None:  # noqa: PLR0911
        try:
            data = json.loads(raw_line)
        except (json.JSONDecodeError, ValueError):
            return None

        if not isinstance(data, dict):
            return None

        ts = datetime.now(tz=timezone.utc)
        t = data.get("type", "")

        # Soft rate-limit warning (periodic usage envelope)
        if t == "rate_limit_event":
            info = data.get("rate_limit_info", {})
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
