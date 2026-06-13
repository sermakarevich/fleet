import json
from datetime import datetime, timezone
from pathlib import Path

from fleet.coders.base import Coder
from fleet.schemas import Event, Task

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
_INSTRUCTION_PATH = _TEMPLATES_DIR / "INSTRUCTION.md"
_HEADER_PATH = _TEMPLATES_DIR / "coder_header.md.tmpl"
_ISOLATED_PROTOCOL_PATH = _TEMPLATES_DIR / "ISOLATED_PROTOCOL.md"

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

    def __init__(
        self,
        model: str = "gpt-oss:20b",
        ollama_url: str = _DEFAULT_OLLAMA_URL,
        context_limit: int = 128_000,
        default_model: str = "gpt-oss:20b",
    ) -> None:
        self.model = model
        self.ollama_url = ollama_url
        self.context_limit = context_limit
        self.default_model = default_model

    def build_argv(self, task: Task, task_dir: Path) -> list[str]:
        artifacts_dir = task_dir / "artifacts"
        instructions = _INSTRUCTION_PATH.read_text(encoding="utf-8").strip()
        invocation_line = f"Invocation directory: {task.cwd}" if task.cwd else ""
        header = (
            _HEADER_PATH.read_text(encoding="utf-8")
            .format(
                task_id=task.id,
                task_title=task.title,
                task_description=task.description or "",
                task_dir=task_dir,
                artifacts_dir=artifacts_dir,
                invocation_line=invocation_line,
            )
            .strip()
        )
        prompt = f"{header}\n\n---\n\n{instructions}"
        if (task_dir / ".worktree").exists():
            isolated = _ISOLATED_PROTOCOL_PATH.read_text(encoding="utf-8").strip()
            prompt += f"\n\n---\n\n{isolated}"
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

        base_url = self.ollama_url

        # Merge models from any existing ollama-rtx entry so concurrent tasks
        # with different models do not clobber each other's models map.
        existing_provider: dict = existing.get("provider", {})
        existing_ollama: dict = existing_provider.get(_PROVIDER_ID, {})
        merged_models: dict = dict(existing_ollama.get("models", {}))
        merged_models[map_key] = {
            "name": map_key,
            "tools": True,
            "limit": {"context": int(self.context_limit), "output": 8192},
        }

        ollama_entry = {
            "npm": "@ai-sdk/openai-compatible",
            "name": "Ollama (rtx)",
            "options": {"baseURL": base_url},
            "models": merged_models,
        }

        provider: dict = dict(existing.get("provider", {}))
        provider[_PROVIDER_ID] = ollama_entry

        fleet_root = Path(__file__).parent.parent.parent.parent
        ask_human_entry = {
            "type": "local",
            "command": [
                "uv",
                "--directory",
                str(fleet_root),
                "run",
                "python",
                "-m",
                "fleet.ask_human.server",
            ],
            "enabled": True,
        }
        mcp: dict = dict(existing.get("mcp", {}))
        mcp["ask-human"] = ask_human_entry

        result: dict = {}
        if "$schema" not in existing:
            result["$schema"] = "https://opencode.ai/config.json"
        for k, v in existing.items():
            if k not in ("provider", "permission", "mcp"):
                result[k] = v

        # Merge permission block instead of discarding the owner's settings.
        existing_permission: dict = existing.get("permission", {})
        result["permission"] = {**existing_permission, "external_directory": "allow"}

        result["provider"] = provider
        result["mcp"] = mcp

        # Atomic write via tmp-sibling + replace to avoid torn reads.
        tmp = target.with_name(target.name + ".tmp")
        tmp.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        tmp.replace(target)

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
            reason = part.get("reason")
            if reason == "length":
                return Event(kind="error", raw=data, ts=ts, session_id=session_id)
            if reason != "stop":
                tokens = part.get("tokens", {})
                if not tokens:
                    return None
                cache = tokens.get("cache", {})
                usage = {
                    "input_tokens": tokens.get("input", 0),
                    "output_tokens": tokens.get("output", 0),
                    "cache_creation_input_tokens": cache.get("write", 0),
                    "cache_read_input_tokens": cache.get("read", 0),
                }
                return Event(
                    kind="assistant_text",
                    raw=data,
                    ts=ts,
                    session_id=session_id,
                    usage=usage,
                )
            tokens = part.get("tokens", {})
            cache = tokens.get("cache", {})
            usage = {
                "input_tokens": tokens.get("input", 0),
                "output_tokens": tokens.get("output", 0),
                "cache_creation_input_tokens": cache.get("write", 0),
                "cache_read_input_tokens": cache.get("read", 0),
            }
            return Event(
                kind="session_ended",
                raw=data,
                ts=ts,
                session_id=session_id,
                usage=usage,
            )

        if t == "error":
            return Event(kind="error", raw=data, ts=ts)

        return None
