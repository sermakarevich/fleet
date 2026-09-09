import json
import os
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar

from fleet.coders.base import CoderSpec, context_limit_for, lookup_handler, prompt_context
from fleet.coders.env import bedrock_env, fleet_env
from fleet.coders.model_ref import resolve_model
from fleet.coders.settings import OpencodeSettings
from fleet.core.launch import LaunchPlan
from fleet.core.limits import RATE_LIMIT_DEFAULT_SLEEP_SEC
from fleet.core.task import Event, EventKind, Task, TaskOutcome, TaskOutcomeRecord
from fleet.integrations.mcp_servers import fleet_mcp_servers
from fleet.prompts import render

_PROVIDER_ID = "ollama-rtx"
_BEDROCK_PROVIDER_ID = "amazon-bedrock"

_DEFAULT_MODEL = "gpt-oss:20b"
_DEFAULT_WINDOW = 128_000
_LOG_TAIL_BYTES = 256 * 1024

_TIMESTAMP_RE = re.compile(r"timestamp=(\S+)")
_LEVEL_RE = re.compile(r"level=(\S+)")
_MODEL_ID_RE = re.compile(r"modelID=(\S+)")
_SESSION_ID_RE = re.compile(r"session\.id=(\S+)")

_RATE_LIMIT_MARKERS = ("rate_limit_exceeded", "Rate limit exceeded")
_CONNECT_ERROR_MARKERS = ("Cannot connect to API", "socket connection was closed")


def _strip_provider_prefix(model: str) -> str:
    """Return the bare model id, stripping a single leading `<provider>/` prefix."""
    if "/" in model:
        return model.split("/", 1)[1]
    return model


def classify_opencode_log_lines(
    lines: list[str], *, since: datetime, model: str, session_id: str | None = None
) -> TaskOutcomeRecord | None:
    """Classify tailed opencode.log lines for provider rate-limit/connect errors.

    The log file is shared by every opencode session running on the machine.
    When this task's opencode ``session_id`` is known, lines tagged with a
    different ``session.id`` are another task's problem and are skipped;
    otherwise the time window (`since`) plus model filter (`model`) is the
    only heuristic. A false positive only causes the runner to
    release-and-retry the task; it never blocks it.
    """
    target_model = _strip_provider_prefix(model)
    for line in lines:
        level_match = _LEVEL_RE.search(line)
        if not level_match or level_match.group(1) != "ERROR":
            continue
        if session_id:
            sess_match = _SESSION_ID_RE.search(line)
            if sess_match and sess_match.group(1) != session_id:
                continue

        ts_match = _TIMESTAMP_RE.search(line)
        if not ts_match:
            continue
        try:
            ts = datetime.fromisoformat(ts_match.group(1).replace("Z", "+00:00"))
        except ValueError:
            continue
        if ts < since:
            continue

        model_match = _MODEL_ID_RE.search(line)
        if not model_match or model_match.group(1) != target_model:
            continue

        if any(marker in line for marker in _RATE_LIMIT_MARKERS):
            return TaskOutcomeRecord(
                outcome=TaskOutcome.RATE_LIMIT,
                reason="opencode provider rate limit",
                resets_at=int(time.time()) + RATE_LIMIT_DEFAULT_SLEEP_SEC,
            )
        if any(marker in line for marker in _CONNECT_ERROR_MARKERS):
            return TaskOutcomeRecord(
                outcome=TaskOutcome.FAILURE,
                exit_code=None,
                reason=f"opencode provider unreachable: {line[:120]}",
            )
    return None


def _model_ref(model: str, default: str):
    """This coder's ModelRef: bare names route to the ollama-rtx provider."""
    return resolve_model(model, default, default_provider=_PROVIDER_ID)


def _session_started(data: dict) -> Event | None:
    """A step_start fires at the beginning of every LLM step (repeats per step)."""
    return Event(
        kind=EventKind.SESSION_STARTED,
        raw=data,
        ts=datetime.now(tz=UTC),
        session_id=data.get("sessionID"),
    )


def _assistant_text(data: dict) -> Event | None:
    """A streamed text part."""
    return Event(
        kind=EventKind.ASSISTANT_TEXT,
        raw=data,
        ts=datetime.now(tz=UTC),
        session_id=data.get("sessionID"),
    )


def _tool_event(data: dict) -> Event | None:
    """A tool part: completed and error states map to result/error, else use."""
    part = data.get("part", {})
    if not isinstance(part, dict) or part.get("type") != "tool":
        return None
    state = part.get("state", {})
    status = state.get("status") if isinstance(state, dict) else None
    tool_name = part.get("tool")
    if status == "completed":
        return Event(
            kind=EventKind.TOOL_RESULT, raw=data, ts=datetime.now(tz=UTC), tool_name=tool_name
        )
    if status == "error":
        return Event(kind=EventKind.ERROR, raw=data, ts=datetime.now(tz=UTC), tool_name=tool_name)
    return Event(kind=EventKind.TOOL_USE, raw=data, ts=datetime.now(tz=UTC), tool_name=tool_name)


def _usage_of(tokens: object) -> dict:
    """Map opencode's token block to fleet's usage dict."""
    block = tokens if isinstance(tokens, dict) else {}
    cache = block.get("cache", {})
    if not isinstance(cache, dict):
        cache = {}
    return {
        "input_tokens": block.get("input", 0),
        "output_tokens": block.get("output", 0),
        "cache_creation_input_tokens": cache.get("write", 0),
        "cache_read_input_tokens": cache.get("read", 0),
    }


def _step_finish(data: dict) -> Event | None:
    """A finished step: length is an error, stop ends the session, else usage."""
    part = data.get("part", {})
    if not isinstance(part, dict):
        return None
    session_id = data.get("sessionID")
    if part.get("reason") == "length":
        return Event(kind=EventKind.ERROR, raw=data, ts=datetime.now(tz=UTC), session_id=session_id)
    if part.get("reason") != "stop":
        tokens = part.get("tokens", {})
        if not tokens:
            return None
        return Event(
            kind=EventKind.ASSISTANT_TEXT,
            raw=data,
            ts=datetime.now(tz=UTC),
            session_id=session_id,
            usage=_usage_of(tokens),
        )
    return Event(
        kind=EventKind.SESSION_ENDED,
        raw=data,
        ts=datetime.now(tz=UTC),
        session_id=session_id,
        usage=_usage_of(part.get("tokens", {})),
    )


def _error(data: dict) -> Event | None:
    """A top-level error envelope."""
    return Event(kind=EventKind.ERROR, raw=data, ts=datetime.now(tz=UTC))


EVENT_MAP: dict[tuple[str, str | None], Callable[[dict], Event | None]] = {
    ("step_start", None): _session_started,
    ("text", None): _assistant_text,
    ("tool_use", None): _tool_event,
    ("step_finish", None): _step_finish,
    ("error", None): _error,
}


@dataclass(frozen=True)
class OpencodeCoder:
    """The opencode CLI coder: JSON run argv, config-via-env, log-file health probe."""

    spec: ClassVar[CoderSpec] = CoderSpec(
        name="opencode", default_model=_DEFAULT_MODEL, context_limit=_DEFAULT_WINDOW
    )

    fleet_home: Path
    model: str = _DEFAULT_MODEL
    default_model: str = _DEFAULT_MODEL
    settings: OpencodeSettings = field(default_factory=OpencodeSettings)
    context_limit_override: int | None = None

    @property
    def context_limit(self) -> int:
        """Effective window: explicit override wins, else the per-model table."""
        if self.context_limit_override is not None:
            return self.context_limit_override
        bedrock = self.settings.bedrock
        if self.is_bedrock and bedrock is not None and bedrock.context_limit is not None:
            return bedrock.context_limit
        return context_limit_for(OpencodeCoder.spec, self.model)

    @property
    def is_bedrock(self) -> bool:
        """True when the model routes to Amazon Bedrock instead of Ollama."""
        return _model_ref(self.model, self.default_model).provider == _BEDROCK_PROVIDER_ID

    def build_argv(self, task: Task, task_dir: Path, plan: LaunchPlan | None = None) -> list[str]:
        mode, ctx = prompt_context(task, task_dir, plan)
        prompt = render(mode, ctx)
        full_id = _model_ref(self.model, self.default_model).full_id
        argv = ["opencode", "run", "--format", "json", "--model", full_id]
        if ctx.workdir:
            argv += ["--dir", ctx.workdir]
        argv.append(prompt)
        return argv

    def env(self, task: Task, task_dir: Path) -> dict[str, str]:
        bedrock = self.settings.bedrock if self.is_bedrock else None
        return {
            **fleet_env(task, task_dir),
            # Provider + MCP config is injected via env instead of an
            # opencode.json written into the task cwd, so we no longer
            # pollute project directories. opencode loads this as a
            # "local"-scope config and merges it with global/project config.
            "OPENCODE_CONFIG_CONTENT": json.dumps(self._build_config()),
            **bedrock_env(bedrock),
        }

    def _build_config(self) -> dict:
        """Build the opencode config dict (provider + MCP + permission).

        Self-contained per task -- no on-disk file to merge with, so concurrent
        tasks with different models can't clobber each other.
        """
        ref = _model_ref(self.model, self.default_model)
        map_key = ref.name if ref.provider == _PROVIDER_ID else self.default_model

        base_url = self.settings.ollama_url

        merged_models: dict = {}
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

        provider: dict = {}
        provider[_PROVIDER_ID] = ollama_entry

        if self.is_bedrock:
            bedrock_models: dict = {}
            bedrock_models[ref.name] = {
                "name": ref.name,
                "tools": True,
                "limit": {"context": int(self.context_limit), "output": 8192},
            }
            provider[_BEDROCK_PROVIDER_ID] = {
                "name": "Amazon Bedrock",
                "models": bedrock_models,
            }

        shared = fleet_mcp_servers(self.fleet_home)
        ask_human = shared["ask_human"]
        ask_human_entry = {
            "type": "local",
            "command": [ask_human["command"], *ask_human["args"]],
            "environment": dict(ask_human["env"]),
            "enabled": True,
        }
        mcp: dict = {}
        mcp["ask-human"] = ask_human_entry

        web_fetch = shared["web_fetch"]
        web_fetch_entry = {
            "type": "local",
            "command": [web_fetch["command"], *web_fetch["args"]],
            "environment": {
                **web_fetch["env"],
                "FLEET_WEBFETCH_MODEL": ref.name,
                "FLEET_WEBFETCH_OLLAMA_URL": base_url,
            },
            "enabled": True,
        }
        mcp["web_fetch"] = web_fetch_entry

        playwright_entry = {
            "type": "local",
            "command": [
                "npx",
                "-y",
                "@playwright/mcp@latest",
                "--headless",
                "--isolated",
            ],
            "enabled": True,
        }
        mcp["playwright"] = playwright_entry

        claude_code_entry = {
            "type": "local",
            "command": [
                "uv",
                "run",
                "--script",
                str(Path.home() / ".claude" / "mcp-servers" / "claude_code" / "server.py"),
            ],
            "enabled": True,
        }
        mcp["claude_code"] = claude_code_entry

        result: dict = {
            "$schema": "https://opencode.ai/config.json",
            "permission": {"external_directory": "allow"},
            "provider": provider,
            "mcp": mcp,
        }
        return result

    def normalize_event(self, raw_line: str) -> Event | None:
        """Parse one stdout line via EVENT_MAP keyed on (type, subtype)."""
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

    def probe_health(
        self,
        task: Task,
        task_dir: Path,
        since: datetime,
        session_id: str | None = None,
    ) -> TaskOutcomeRecord | None:
        """Detect provider rate-limit/connect errors opencode swallows silently.

        `opencode run --format json` never emits a provider error into its
        JSON stream: on a rate limit or connection failure it logs to
        opencode.log and the process hangs forever with no stdout/stderr.
        Read the tail of that log and classify lines logged after `since`
        (the last stdout event). Transient rate limits that opencode retried
        and recovered from are older than the last event and are ignored.
        `session_id` is this run's session (tracked by the event stream) so a
        sibling task's rate-limit errors are never attributed to us.
        """
        log_path = self.settings.log_file
        if not log_path.exists():
            return None

        with log_path.open("rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - _LOG_TAIL_BYTES))
            tail = f.read().decode("utf-8", errors="replace")

        lines = tail.splitlines()
        model = task.model or self.model
        return classify_opencode_log_lines(lines, since=since, model=model, session_id=session_id)
