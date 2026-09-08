import json
import os
from datetime import UTC, datetime
from pathlib import Path

from fleet.coders.base import Coder, render_prompt
from fleet.core.launch import LaunchPlan
from fleet.core.task import Event, Task

_DEFAULT_OLLAMA_URL = "http://127.0.0.1:11435/v1"
# pi reads provider config from <agent-dir>/models.json. The provider id is the
# first path segment of the --model argument (e.g. "ollama/qwen3.6:latest").
_PROVIDER_ID = "ollama"
_BEDROCK_PROVIDER_ID = "amazon-bedrock"

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


def _pi_agent_dir() -> Path:
    """Directory pi reads its config from (models.json, settings.json).

    Honors PI_CODING_AGENT_DIR so this writer and the spawned subprocess (which
    inherits os.environ via the runner) always agree on the location. Defaults
    to ~/.pi/agent, the path verified to load custom providers.
    """
    override = os.environ.get("PI_CODING_AGENT_DIR")
    return Path(override) if override else Path.home() / ".pi" / "agent"


def _map_usage(usage: object) -> dict | None:
    """Map pi's per-message usage block to fleet's usage dict, or None."""
    if not isinstance(usage, dict):
        return None
    return {
        "input_tokens": usage.get("input", 0),
        "output_tokens": usage.get("output", 0),
        "cache_creation_input_tokens": usage.get("cacheWrite", 0),
        "cache_read_input_tokens": usage.get("cacheRead", 0),
    }


class PiCoder(Coder):
    name = "pi"
    context_limit = 128_000
    default_model = "qwen3.6:latest"

    @classmethod
    def context_limit_for(
        cls, model: str | None, overrides: dict[str, int] | None = None
    ) -> int:
        """Context window for the given model string.

        Resolves through ``core.context_window.resolve_window`` (per-model
        table, Bedrock ids included) with the class ``context_limit`` as
        the fallback, so supervisor and UI share one denominator.
        """
        from fleet.core.context_window import resolve_window

        return resolve_window(model, overrides, cls.context_limit)

    def __init__(
        self,
        model: str = "qwen3.6:latest",
        ollama_url: str = _DEFAULT_OLLAMA_URL,
        context_limit: int | None = None,
        default_model: str = "qwen3.6:latest",
        bedrock_region: str = "",
        bedrock_profile: str = "",
        bedrock_context_limit: int | None = None,
    ) -> None:
        # bedrock_* are accepted because supervisor._resolve_coder passes the
        # same kwargs to opencode and pi; they are inert for ollama routing.
        self.model = model
        self.ollama_url = ollama_url
        self.default_model = default_model
        self.bedrock_region = bedrock_region
        self.bedrock_profile = bedrock_profile
        resolved = type(self).context_limit_for(model)
        if self.is_bedrock:
            self.context_limit = (
                bedrock_context_limit if bedrock_context_limit is not None else resolved
            )
        else:
            self.context_limit = (
                context_limit if context_limit is not None else resolved
            )

    @property
    def is_bedrock(self) -> bool:
        full_id, _ = _resolve_model(self.model, self.default_model)
        return full_id.split("/", 1)[0] == _BEDROCK_PROVIDER_ID

    def build_argv(
        self, task: Task, task_dir: Path, plan: LaunchPlan | None = None
    ) -> list[str]:
        prompt = render_prompt(task, task_dir, plan)
        full_id, _ = _resolve_model(self.model, self.default_model)
        # pi emits one NDJSON event per stdout line in --mode json. `-p` selects
        # non-interactive print mode; the prompt is positional. pi works in the
        # process cwd (set by the runner), so there is no --dir flag.
        return ["pi", "-p", "--mode", "json", "--model", full_id, prompt]

    def env(self, task: Task, task_dir: Path) -> dict[str, str]:
        e = {
            "FLEET_TASK_ID": task.id,
            "FLEET_TASK_DIR": str(task_dir),
        }
        if self.is_bedrock:
            if self.bedrock_profile:
                e["AWS_PROFILE"] = self.bedrock_profile
            if self.bedrock_region:
                e["AWS_REGION"] = self.bedrock_region
        return e

    def write_runtime_config(self, project: Path, task: Task) -> None:
        """Ensure pi's models.json defines the ollama provider used to route.

        Unlike opencode (project-scoped opencode.json), pi reads provider config
        from a global agent dir (~/.pi/agent/models.json, or
        $PI_CODING_AGENT_DIR/models.json). The provider/model entry is merged in,
        preserving any other providers or models already configured. The
        `project` argument is unused: pi's provider config is not project-scoped.
        """
        full_id, local_key = _resolve_model(self.model, self.default_model)
        provider_prefix = full_id.split("/", 1)[0]
        # Only the ollama provider is configured here. Bedrock routing for pi is
        # not supported (its models.json schema differs and is unverified); a
        # bedrock model resolves through pi's own config untouched.
        if provider_prefix != _PROVIDER_ID:
            return

        agent_dir = _pi_agent_dir()
        agent_dir.mkdir(parents=True, exist_ok=True)
        target = agent_dir / "models.json"

        existing: dict = {}
        if target.exists():
            try:
                existing = json.loads(target.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                existing = {}
        if not isinstance(existing, dict):
            existing = {}

        providers: dict = dict(existing.get("providers", {}))
        existing_ollama: dict = providers.get(_PROVIDER_ID, {})
        existing_models = existing_ollama.get("models", [])
        if not isinstance(existing_models, list):
            existing_models = []

        # Merge model ids (dedup by id) so concurrent tasks with different
        # models do not clobber each other's entries.
        merged_models = [m for m in existing_models if isinstance(m, dict)]
        if not any(m.get("id") == local_key for m in merged_models):
            merged_models.append({"id": local_key})

        providers[_PROVIDER_ID] = {
            "baseUrl": self.ollama_url,
            "api": "openai-completions",
            "apiKey": "ollama",
            "compat": {
                "supportsDeveloperRole": False,
                "supportsReasoningEffort": False,
            },
            "models": merged_models,
        }

        result = dict(existing)
        result["providers"] = providers

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

        ts = datetime.now(tz=UTC)
        t = data.get("type", "")

        # Session header: {"type":"session","id":<uuid>,"cwd":...}.
        if t == "session":
            return Event(
                kind="session_started", raw=data, ts=ts, session_id=data.get("id")
            )

        # A completed message. role/usage/content are nested under .message;
        # incremental deltas arrive as message_update and are skipped below.
        if t == "message_end":
            msg = data.get("message", {})
            if not isinstance(msg, dict) or msg.get("role") != "assistant":
                # user echoes and toolResult duplicates (tool_execution_end
                # already emits the tool_result) are dropped.
                return None
            usage = _map_usage(msg.get("usage"))
            if msg.get("stopReason") == "length":
                return Event(kind="error", raw=data, ts=ts, usage=usage)
            return Event(kind="assistant_text", raw=data, ts=ts, usage=usage)

        if t == "tool_execution_start":
            return Event(
                kind="tool_use", raw=data, ts=ts, tool_name=data.get("toolName")
            )

        if t == "tool_execution_end":
            kind = "error" if data.get("isError") else "tool_result"
            return Event(kind=kind, raw=data, ts=ts, tool_name=data.get("toolName"))

        # Final event of a run; per-message usage already flowed via message_end.
        if t == "agent_end":
            return Event(kind="session_ended", raw=data, ts=ts)

        if t == "error":
            return Event(kind="error", raw=data, ts=ts)

        # agent_start / turn_start / turn_end / message_start / message_update.
        return None
