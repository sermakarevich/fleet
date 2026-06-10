from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Literal

LOG_ROOT = "logging"

RATE_LIMIT_THRESHOLD_PCT: int = 90
RETRY_LIMIT: int = 2
CONFIG_POLL_INTERVAL_SEC: int = 5
CLAIM_POLL_INTERVAL_SEC: int = 5
SHUTDOWN_GRACE_SEC: int = 30
RATE_LIMIT_DEFAULT_SLEEP_SEC: int = 300
STATUS_LOG_INTERVAL_SEC: int = 30


@dataclass
class Task:
    id: str
    title: str
    description: str | None
    status: str
    cwd: str | None = None
    coder: str | None = None
    model: str | None = None


EventKind = Literal[
    "assistant_text",
    "tool_use",
    "tool_result",
    "thinking",
    "rate_limit",
    "rate_limit_info",
    "context_pressure",
    "session_started",
    "session_ended",
    "error",
    "result",
]


@dataclass
class Event:
    kind: EventKind
    raw: dict
    ts: datetime
    session_id: str | None = None
    tool_name: str | None = None
    # {input_tokens, output_tokens, cache_creation_input_tokens, cache_read_input_tokens}
    usage: dict | None = None
    # {usage_pct: float|None, resets_at: int|None, status: str|None}
    rate_info: dict | None = None
    extra: dict = field(default_factory=dict)


class TaskOutcome(Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    RATE_LIMIT = "rate_limit"
    CONTEXT_PRESSURE = "context_pressure"
    BLOCKED_BY_AGENT = "blocked_by_agent"
    KILLED = "killed"


@dataclass
class TaskOutcomeRecord:
    outcome: TaskOutcome
    exit_code: int | None = None
    reason: str = ""
    resets_at: int | None = None
    stderr_tail: str | None = None


@dataclass
class RuntimeConfig:
    max_concurrent: int = 3
    model: str = "sonnet"
    coder: str = "claude"
    context_pressure_threshold_pct: int = 90
    telegram_chat_id: str = ""
    telegram_allowed_ids: str = ""
    telegram_default_cwd: str = ""
