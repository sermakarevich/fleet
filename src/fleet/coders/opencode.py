import json
import os
from datetime import datetime, timezone
from pathlib import Path

from fleet.coders.base import Coder
from fleet.schemas import Event, Task

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
_INSTRUCTION_PATH = _TEMPLATES_DIR / "INSTRUCTION.md"
_HEADER_PATH = _TEMPLATES_DIR / "coder_header.md.tmpl"

_DEFAULT_OLLAMA_URL = "http://127.0.0.1:11435/v1"
_PROVIDER_ID = "ollama-rtx"

# Fleet's global RuntimeConfig.model defaults to "sonnet" and leaks into every
# coder via supervisor._resolve_coder; these are Claude aliases, never valid
# ollama model names.
_CLAUDE_ALIASES = frozenset({"sonnet", "opus", "haiku"})


def _resolve_model(model: str, default: str) -> tuple[str, str]:
    """Return (full_id, provider_local_key) for the given model string."""
    if model in _CLAUDE_ALIASES:
        model = default
    if "/" in model:
        prefix, local_key = model.split("/", 1)
        return model, local_key
    return f"{_PROVIDER_ID}/{model}", model


class OpencodeCoder(Coder):
    name = "opencode"
    context_limit = 128_000
    default_model = "gpt-oss:20b"

    def __init__(self, model: str = "gpt-oss:20b") -> None:
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
        full_id, _ = _resolve_model(self.model, self.default_model)
        argv = ["opencode", "run", "--format", "json", "--model", full_id]
        if task.cwd:
            argv += ["--dir", task.cwd]
        argv.append(prompt)
        return argv

    def env(self, task: Task, task_dir: Path) -> dict[str, str]:
        return {
            "FLEET_TASK_ID": task.id,
            "FLEET_TASK_DIR": str(task_dir),
            "FLEET_ARTIFACT_DIR": str(task_dir / "artifacts"),
        }

    def write_runtime_config(self, project: Path, task: object) -> None:
        """Write/refresh the ollama-rtx provider entry in project-root opencode.json."""
        target = project / "opencode.json"
        existing: dict = {}
        if target.exists():
            try:
                existing = json.loads(target.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                existing = {}

        full_id, local_key = _resolve_model(self.model, self.default_model)
        provider_prefix = full_id.split("/", 1)[0]
        map_key = local_key if provider_prefix == _PROVIDER_ID else self.default_model

        base_url = os.environ.get("FLEET_OPENCODE_OLLAMA_URL", _DEFAULT_OLLAMA_URL)

        ollama_entry = {
            "npm": "@ai-sdk/openai-compatible",
            "name": "Ollama (rtx)",
            "options": {"baseURL": base_url},
            "models": {map_key: {"name": map_key, "tools": True}},
        }

        provider: dict = dict(existing.get("provider", {}))
        provider[_PROVIDER_ID] = ollama_entry

        result: dict = {}
        if "$schema" not in existing:
            result["$schema"] = "https://opencode.ai/config.json"
        for k, v in existing.items():
            if k != "provider":
                result[k] = v
        result["provider"] = provider

        target.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

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
        part = data.get("part", {})
        session_id = data.get("sessionID")

        # step_start fires at the beginning of every LLM step (repeats per step).
        # runner.py only logs session_started, so repeating is safe.
        if t == "step_start":
            return Event(kind="session_started", raw=data, ts=ts, session_id=session_id)

        if t == "text":
            return Event(kind="assistant_text", raw=data, ts=ts, session_id=session_id)

        if t == "tool_use" and part.get("type") == "tool":
            status = part.get("state", {}).get("status")
            tool_name = part.get("tool")
            if status == "completed":
                return Event(kind="tool_result", raw=data, ts=ts, tool_name=tool_name)
            if status == "error":
                return Event(kind="error", raw=data, ts=ts, tool_name=tool_name)
            return Event(kind="tool_use", raw=data, ts=ts, tool_name=tool_name)

        if t == "step_finish":
            if part.get("reason") != "stop":
                return None
            tokens = part.get("tokens", {})
            cache = tokens.get("cache", {})
            usage = {
                "input_tokens": tokens.get("input", 0),
                "output_tokens": tokens.get("output", 0),
                "cache_creation_input_tokens": cache.get("write", 0),
                "cache_read_input_tokens": cache.get("read", 0),
            }
            return Event(kind="session_ended", raw=data, ts=ts, session_id=session_id, usage=usage)

        if t == "error":
            return Event(kind="error", raw=data, ts=ts)

        return None
