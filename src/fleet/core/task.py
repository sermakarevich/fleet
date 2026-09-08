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
    # Bead type ("task", "bug", "feature", "epic", "chore", ...); routes to a
    # worker family in workers/__init__.py::FAMILIES.
    type: str | None = None
    # Optional metadata override (fleet_worker) naming the family directly.
    worker: str | None = None
    # Per-task wall-clock override, minutes (bd metadata fleet_max_attempt_minutes).
    # None means "use RuntimeConfig.max_attempt_minutes".
    max_attempt_minutes: int | None = None
    # ISO timestamp: claim_next must skip this task while now < retry_after.
    retry_after: str | None = None
    # Isolation opt-out (bd metadata fleet_isolation). "none" disables the
    # worktree even when config.isolation="worktree"; None means "no override".
    isolation: str | None = None
    # Triage ignore: ISO timestamp or "forever" (task.json `ignore_until`).
    # While active the supervisor's triage loop skips this bead.
    ignore_until: str | None = None
    # Git isolation info, mirrored from task.json (queue.set_isolation_info).
    # None when the task is not isolated (non-git cwd or opted out).
    repo_root: str | None = None
    base_ref: str | None = None
    worktree_path: str | None = None


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
    PARTIAL = "partial"
    TERMINAL = "terminal"
    # The observer worker woke before its epic's children were all
    # terminal: release the bead at once, count nothing, comment nothing.
    WAITING = "waiting"


@dataclass
class TaskOutcomeRecord:
    outcome: TaskOutcome
    exit_code: int | None = None
    reason: str = ""
    resets_at: int | None = None
    stderr_tail: str | None = None
    # Set when RESULT.json declared status=done: the worker's own summary,
    # telling retry_policy to close the bead itself rather than count
    # towards the no-close rounds.
    close_reason: str | None = None
