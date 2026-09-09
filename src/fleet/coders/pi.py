import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar

from fleet.coders.base import CoderSpec, context_limit_for, lookup_handler, prompt_context
from fleet.coders.env import bedrock_env, fleet_env
from fleet.coders.model_ref import resolve_model
from fleet.coders.settings import PiSettings
from fleet.core.errors import Json
from fleet.core.launch import LaunchPlan
from fleet.core.task import Event, EventKind, Task
from fleet.prompts import render

# pi reads provider config from <agent-dir>/models.json. The provider id is the
# first path segment of the --model argument (e.g. "ollama/qwen3.6:latest").
_PROVIDER_ID = "ollama"
_BEDROCK_PROVIDER_ID = "amazon-bedrock"

_DEFAULT_MODEL = "qwen3.6:latest"
_DEFAULT_WINDOW = 128_000


def _model_ref(model: str, default: str):
    """This coder's ModelRef: bare names route to the ollama provider."""
    return resolve_model(model, default, default_provider=_PROVIDER_ID)


def _map_usage(usage: Json) -> dict | None:
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
        kind=EventKind.SESSION_STARTED,
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
        return Event(kind=EventKind.ERROR, raw=data, ts=datetime.now(tz=UTC), usage=usage)
    return Event(kind=EventKind.ASSISTANT_TEXT, raw=data, ts=datetime.now(tz=UTC), usage=usage)


def _tool_start(data: dict) -> Event | None:
    """A tool invocation started."""
    return Event(
        kind=EventKind.TOOL_USE, raw=data, ts=datetime.now(tz=UTC), tool_name=data.get("toolName")
    )


def _tool_end(data: dict) -> Event | None:
    """A tool invocation finished; errors surface as error events."""
    if data.get("isError"):
        return Event(
            kind=EventKind.ERROR, raw=data, ts=datetime.now(tz=UTC), tool_name=data.get("toolName")
        )
    return Event(
        kind=EventKind.TOOL_RESULT,
        raw=data,
        ts=datetime.now(tz=UTC),
        tool_name=data.get("toolName"),
    )


def _agent_end(data: dict) -> Event | None:
    """Final event of a run; per-message usage already flowed via message_end."""
    return Event(kind=EventKind.SESSION_ENDED, raw=data, ts=datetime.now(tz=UTC))


def _error(data: dict) -> Event | None:
    """A top-level error envelope."""
    return Event(kind=EventKind.ERROR, raw=data, ts=datetime.now(tz=UTC))


EVENT_MAP: dict[tuple[str, str | None], Callable[[dict], Event | None]] = {
    ("session", None): _session_started,
    ("message_end", None): _message_end,
    ("tool_execution_start", None): _tool_start,
    ("tool_execution_end", None): _tool_end,
    ("agent_end", None): _agent_end,
    ("error", None): _error,
}


@dataclass(frozen=True)
class PiCoder:
    """The pi CLI coder: NDJSON events, provider config in the agent dir."""

    spec: ClassVar[CoderSpec] = CoderSpec(
        name="pi", default_model=_DEFAULT_MODEL, context_limit=_DEFAULT_WINDOW
    )

    fleet_home: Path
    model: str = _DEFAULT_MODEL
    default_model: str = _DEFAULT_MODEL
    settings: PiSettings = field(default_factory=PiSettings)
    context_limit_override: int | None = None

    @property
    def context_limit(self) -> int:
        """Effective window: explicit override wins, else the per-model table."""
        if self.context_limit_override is not None:
            return self.context_limit_override
        bedrock = self.settings.bedrock
        if self.is_bedrock and bedrock is not None and bedrock.context_limit is not None:
            return bedrock.context_limit
        return context_limit_for(PiCoder.spec, self.model)

    @property
    def is_bedrock(self) -> bool:
        """True when the model routes to Amazon Bedrock instead of Ollama."""
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
        bedrock = self.settings.bedrock if self.is_bedrock else None
        return {
            **fleet_env(task, task_dir),
            **bedrock_env(bedrock),
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

        agent_dir = self.settings.agent_dir
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
            "baseUrl": self.settings.ollama_url,
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
