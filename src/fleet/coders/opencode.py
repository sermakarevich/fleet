import json
import os
import re
import time
from datetime import UTC, datetime
from pathlib import Path

from fleet.coders.base import Coder, render_prompt
from fleet.core.launch import LaunchPlan
from fleet.core.limits import RATE_LIMIT_DEFAULT_SLEEP_SEC
from fleet.core.task import Event, Task, TaskOutcome, TaskOutcomeRecord

_DEFAULT_OLLAMA_URL = "http://127.0.0.1:11435/v1"
_PROVIDER_ID = "ollama-rtx"
_BEDROCK_PROVIDER_ID = "amazon-bedrock"

_DEFAULT_OPENCODE_LOG_FILE = str(
    Path.home() / ".local" / "share" / "opencode" / "log" / "opencode.log"
)
_LOG_TAIL_BYTES = 256 * 1024

_TIMESTAMP_RE = re.compile(r"timestamp=(\S+)")
_LEVEL_RE = re.compile(r"level=(\S+)")
_MODEL_ID_RE = re.compile(r"modelID=(\S+)")

_RATE_LIMIT_MARKERS = ("rate_limit_exceeded", "Rate limit exceeded")
_CONNECT_ERROR_MARKERS = ("Cannot connect to API", "socket connection was closed")


def _strip_provider_prefix(model: str) -> str:
    """Return the bare model id, stripping a single leading `<provider>/` prefix."""
    if "/" in model:
        return model.split("/", 1)[1]
    return model


def classify_opencode_log_lines(
    lines: list[str], *, since: datetime, model: str
) -> TaskOutcomeRecord | None:
    """Classify tailed opencode.log lines for provider rate-limit/connect errors.

    The log file is shared by every opencode session running on the machine,
    so the time window (`since`) plus model filter (`model`) is only a
    heuristic to attribute a line to this task's run. A false positive only
    causes the runner to release-and-retry the task; it never blocks it.
    """
    target_model = _strip_provider_prefix(model)
    for line in lines:
        level_match = _LEVEL_RE.search(line)
        if not level_match or level_match.group(1) != "ERROR":
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
    bedrock_context_limit = 200_000
    default_model = "gpt-oss:20b"

    @classmethod
    def context_limit_for(cls, model: str | None) -> int:
        """Return the context limit for the given model string.

        Bedrock models get the bedrock_context_limit (200k).
        Class-level defaults are intentional here -- serve-side display
        does not read runtime.toml overrides.
        """
        if model and model.split("/", 1)[0] == _BEDROCK_PROVIDER_ID:
            return cls.bedrock_context_limit
        return cls.context_limit

    def __init__(
        self,
        model: str = "gpt-oss:20b",
        ollama_url: str = _DEFAULT_OLLAMA_URL,
        context_limit: int = 128_000,
        default_model: str = "gpt-oss:20b",
        bedrock_region: str = "",
        bedrock_profile: str = "",
        bedrock_context_limit: int = 200_000,
    ) -> None:
        self.model = model
        self.ollama_url = ollama_url
        self.context_limit = context_limit
        self.default_model = default_model
        self.bedrock_region = bedrock_region
        self.bedrock_profile = bedrock_profile
        self.bedrock_context_limit = bedrock_context_limit
        if self.is_bedrock:
            self.context_limit = self.bedrock_context_limit

    @property
    def is_bedrock(self) -> bool:
        full_id, _ = _resolve_model(self.model, self.default_model)
        return full_id.split("/", 1)[0] == _BEDROCK_PROVIDER_ID

    def build_argv(
        self, task: Task, task_dir: Path, plan: LaunchPlan | None = None
    ) -> list[str]:
        prompt = render_prompt(task, task_dir, plan)
        full_id, _ = _resolve_model(self.model, self.default_model)
        argv = ["opencode", "run", "--format", "json", "--model", full_id]
        if task.cwd:
            argv += ["--dir", task.cwd]
        argv.append(prompt)
        return argv

    def env(self, task: Task, task_dir: Path) -> dict[str, str]:
        e = {
            "FLEET_TASK_ID": task.id,
            "FLEET_TASK_DIR": str(task_dir),
            "FLEET_ARTIFACT_DIR": str(task_dir / "artifacts"),
            # Provider + MCP config is injected via env instead of an
            # opencode.json written into the task cwd, so we no longer
            # pollute project directories. opencode loads this as a
            # "local"-scope config and merges it with global/project config.
            "OPENCODE_CONFIG_CONTENT": json.dumps(self._build_config()),
        }
        if self.is_bedrock:
            if self.bedrock_profile:
                e["AWS_PROFILE"] = self.bedrock_profile
            if self.bedrock_region:
                e["AWS_REGION"] = self.bedrock_region
        return e

    def write_runtime_config(self, project: Path, task: object) -> None:
        """No-op: provider/MCP config is injected via OPENCODE_CONFIG_CONTENT in
        env() instead of writing an opencode.json into the project directory.

        Kept for Coder-interface compatibility. Previously this wrote
        ``project/opencode.json``, which polluted every task cwd.
        """
        return None

    def _build_config(self) -> dict:
        """Build the opencode config dict (provider + MCP + permission).

        Self-contained per task -- no on-disk file to merge with, so concurrent
        tasks with different models can't clobber each other.
        """
        full_id, local_key = _resolve_model(self.model, self.default_model)
        provider_prefix = full_id.split("/", 1)[0]
        map_key = local_key if provider_prefix == _PROVIDER_ID else self.default_model

        base_url = self.ollama_url

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
            bedrock_models[local_key] = {
                "name": local_key,
                "tools": True,
                "limit": {"context": int(self.context_limit), "output": 8192},
            }
            provider[_BEDROCK_PROVIDER_ID] = {
                "name": "Amazon Bedrock",
                "models": bedrock_models,
            }

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
                "fleet.integrations.ask_human.server",
            ],
            "enabled": True,
        }
        mcp: dict = {}
        mcp["ask-human"] = ask_human_entry

        web_fetch_entry = {
            "type": "local",
            "command": [
                "uv",
                "--directory",
                str(fleet_root),
                "run",
                "python",
                "-m",
                "fleet.integrations.web_fetch.server",
            ],
            "environment": {
                "FLEET_WEBFETCH_MODEL": local_key,
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
                str(
                    Path.home()
                    / ".claude"
                    / "mcp-servers"
                    / "claude_code"
                    / "server.py"
                ),
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

    def probe_health(
        self, task: Task, task_dir: Path, started_at: datetime
    ) -> TaskOutcomeRecord | None:
        """Detect provider rate-limit/connect errors opencode swallows silently.

        `opencode run --format json` never emits a provider error into its
        JSON stream: on a rate limit or connection failure it logs to
        opencode.log and the process hangs forever with no stdout/stderr.
        Read the tail of that log and classify lines since this run started.
        """
        log_path = Path(os.environ.get("OPENCODE_LOG_FILE", _DEFAULT_OPENCODE_LOG_FILE))
        if not log_path.exists():
            return None

        with log_path.open("rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - _LOG_TAIL_BYTES))
            tail = f.read().decode("utf-8", errors="replace")

        lines = tail.splitlines()
        model = task.model or self.model
        return classify_opencode_log_lines(lines, since=started_at, model=model)
