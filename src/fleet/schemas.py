from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Literal


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
    rate_limit_threshold_pct: int = 90
    retry_limit: int = 3
    config_poll_interval_sec: int = 5
    claim_poll_interval_sec: int = 5
    shutdown_grace_sec: int = 30
    rate_limit_default_sleep_sec: int = 300
    status_log_interval_sec: int = 30
    log_root: str = "logging"
    model: str = "sonnet"
    coder: str = "claude"
