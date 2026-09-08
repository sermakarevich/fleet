import json
import os
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from fleet.coders.base import Coder, base_env, lookup_handler, prompt_context
from fleet.coders.model_ref import resolve_model
from fleet.coders.ollama import DEFAULT_OLLAMA_URL, ollama_env
from fleet.core.context_window import resolve_window
from fleet.core.launch import LaunchPlan
from fleet.core.task import Event, Task
from fleet.prompts import render

# pi reads provider config from <agent-dir>/models.json. The provider id is the
# first path segment of the --model argument (e.g. "ollama/qwen3.6:latest").
_PROVIDER_ID = "ollama"
_BEDROCK_PROVIDER_ID = "amazon-bedrock"


def _model_ref(model: str, default: str):
    """This coder's ModelRef: bare names route to the ollama provider."""
    return resolve_model(model, default, default_provider=_PROVIDER_ID)


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


def _session_started(data: dict) -> Event | None:
    """Session header: {"type":"session","id":<uuid>,"cwd":...}."""
    return Event(
        kind="session_started",
        raw=data,
        ts=datetime.now(tz=UTC),
        session_id=data.get("id"),
    )


def _message_end(data: dict) -> Event | None:
    """A completed message; user echoes and toolResult duplicates are dropped."""
    msg = data.get("message", {})
    if not isinstance(msg, dict) or msg.get("role") != "assistant":
        return None
    usage = _map_usage(msg.get("usage"))
    if msg.get("stopReason") == "length":
        return Event(kind="error", raw=data, ts=datetime.now(tz=UTC), usage=usage)
    return Event(kind="assistant_text", raw=data, ts=datetime.now(tz=UTC), usage=usage)


def _tool_start(data: dict) -> Event | None:
    """A tool invocation started."""
    return Event(kind="tool_use", raw=data, ts=datetime.now(tz=UTC), tool_name=data.get("toolName"))


def _tool_end(data: dict) -> Event | None:
    """A tool invocation finished; errors surface as error events."""
    if data.get("isError"):
        return Event(
            kind="error", raw=data, ts=datetime.now(tz=UTC), tool_name=data.get("toolName")
        )
    return Event(
        kind="tool_result", raw=data, ts=datetime.now(tz=UTC), tool_name=data.get("toolName")
    )


def _agent_end(data: dict) -> Event | None:
    """Final event of a run; per-message usage already flowed via message_end."""
    return Event(kind="session_ended", raw=data, ts=datetime.now(tz=UTC))


def _error(data: dict) -> Event | None:
    """A top-level error envelope."""
    return Event(kind="error", raw=data, ts=datetime.now(tz=UTC))


EVENT_MAP: dict[tuple[str, str | None], Callable[[dict], Event | None]] = {
    ("session", None): _session_started,
    ("message_end", None): _message_end,
    ("tool_execution_start", None): _tool_start,
    ("tool_execution_end", None): _tool_end,
    ("agent_end", None): _agent_end,
    ("error", None): _error,
}


class PiCoder(Coder):
    name = "pi"
    context_limit = 128_000
    default_model = "qwen3.6:latest"

    @classmethod
    def context_limit_for(cls, model: str | None, overrides: dict[str, int] | None = None) -> int:
        """Context window for the given model string.

        Resolves through ``core.context_window.resolve_window`` (per-model
        table, Bedrock ids included) with the class ``context_limit`` as
        the fallback, so supervisor and UI share one denominator.
        """

        return resolve_window(model, overrides, cls.context_limit)

    def __init__(
        self,
        model: str = "qwen3.6:latest",
        ollama_url: str = DEFAULT_OLLAMA_URL,
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
            self.context_limit = context_limit if context_limit is not None else resolved

    @property
    def is_bedrock(self) -> bool:
        return _model_ref(self.model, self.default_model).provider == _BEDROCK_PROVIDER_ID

    def build_argv(self, task: Task, task_dir: Path, plan: LaunchPlan | None = None) -> list[str]:
        mode, ctx = prompt_context(task, task_dir, plan)
        prompt = render(mode, ctx)
        full_id = _model_ref(self.model, self.default_model).full_id
        # pi emits one NDJSON event per stdout line in --mode json. `-p` selects
        # non-interactive print mode; the prompt is positional. pi works in the
        # process cwd (set by the runner), so there is no --dir flag.
        return ["pi", "-p", "--mode", "json", "--model", full_id, prompt]

    def env(self, task: Task, task_dir: Path) -> dict[str, str]:
        return {
            **base_env(task, task_dir),
            **ollama_env(
                is_bedrock=self.is_bedrock,
                bedrock_profile=self.bedrock_profile,
                bedrock_region=self.bedrock_region,
            ),
        }

    def write_runtime_config(self, project: Path, task: Task) -> None:
        """Ensure pi's models.json defines the ollama provider used to route.

        Unlike opencode (project-scoped opencode.json), pi reads provider config
        from a global agent dir (~/.pi/agent/models.json, or
        $PI_CODING_AGENT_DIR/models.json). The provider/model entry is merged in,
        preserving any other providers or models already configured. The
        `project` argument is unused: pi's provider config is not project-scoped.
        """
        ref = _model_ref(self.model, self.default_model)
        # Only the ollama provider is configured here. Bedrock routing for pi is
        # not supported (its models.json schema differs and is unverified); a
        # bedrock model resolves through pi's own config untouched.
        if ref.provider != _PROVIDER_ID:
            return
        local_key = ref.name

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

    def normalize_event(self, raw_line: str) -> Event | None:
        """Parse one stdout line via EVENT_MAP keyed on (type, subtype).

        agent_start / turn_start / turn_end / message_start / message_update
        have no entry and return None.
        """
        if not raw_line.strip():
            return None
        try:
            data = json.loads(raw_line)
        except (json.JSONDecodeError, ValueError):
            return None
        if not isinstance(data, dict):
            return None
        handler = lookup_handler(EVENT_MAP, (data.get("type", ""), data.get("subtype")))
        if handler is None:
            return None
        return handler(data)
