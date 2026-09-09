"""Core task types: Task, Event, outcomes. Called from every layer.

``EventKind`` names every event kind a coder actually emits; ``TaskStatus``
names every bead status; ``AttemptKind`` names attempt journal kinds;
``Json`` is the unvalidated-JSON alias used at parse boundaries.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from fleet.core.errors import Json


class EventKind(StrEnum):
    """One event kind a coder stream actually emits.

    ``RATE_LIMIT`` is the quota-exhausted signal; ``RATE_LIMIT_INFO`` is the
    informational usage snapshot some coders send alongside it. ``RESULT``
    and ``CONTEXT_PRESSURE`` are intentionally absent: result lives in
    RESULT.json (see ``core/result.py``) and context pressure is a task
    outcome (see ``TaskOutcome``), neither is ever emitted as an event.
    """

    ASSISTANT_TEXT = "assistant_text"
    TOOL_USE = "tool_use"
    TOOL_RESULT = "tool_result"
    THINKING = "thinking"
    RATE_LIMIT = "rate_limit"
    RATE_LIMIT_INFO = "rate_limit_info"
    SESSION_STARTED = "session_started"
    SESSION_ENDED = "session_ended"
    ERROR = "error"


class TaskStatus(StrEnum):
    """Bead status as reported by ``bd``."""

    OPEN = "open"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    CLOSED = "closed"
    FAILED = "failed"


class AttemptKind(StrEnum):
    """Attempt journal kind: real work vs. the compaction job's own row."""

    WORK = "work"
    COMPACT = "compact"


@dataclass(frozen=True, slots=True)
class Task:
    """One bead plus its fleet routing metadata."""

    id: str
    title: str
    description: str | None
    status: str
    cwd: str | None = None
    coder: str | None = None
    model: str | None = None
    # Bead type ("task", "bug", "feature", "epic", "chore", ...); routes to a
    # worker family in workers/__init__.py::WORKERS.
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
    # Job gate opt-out (bd metadata fleet_job_gate). "off" skips the human
    # approval gate between design and spawn; None means "gate when enabled".
    job_gate: str | None = None
    # Triage ignore: ISO timestamp or "forever" (task.json `ignore_until`).
    # While active the supervisor's triage loop skips this bead.
    ignore_until: str | None = None
    # Git isolation info, mirrored from task.json (queue.set_isolation_info).
    # None when the task is not isolated (non-git cwd or opted out).
    repo_root: str | None = None
    base_ref: str | None = None
    worktree_path: str | None = None


@dataclass(frozen=True, slots=True)
class Event:
    """One normalized coder-stream event."""

    kind: EventKind | str
    raw: dict
    ts: datetime
    session_id: str | None = None
    tool_name: str | None = None
    # {input_tokens, output_tokens, cache_creation_input_tokens, cache_read_input_tokens}
    usage: dict | None = None
    # {usage_pct: float|None, resets_at: int|None, status: str|None}
    rate_info: dict | None = None
    extra: dict = field(default_factory=dict)

    @property
    def kind_value(self) -> str:
        """The event kind as plain text for JSON edges."""
        return self.kind.value if isinstance(self.kind, EventKind) else str(self.kind)


class TaskOutcome(StrEnum):
    """How one worker attempt ended."""

    SUCCESS = "success"
    FAILURE = "failure"
    RATE_LIMIT = "rate_limit"
    CONTEXT_PRESSURE = "context_pressure"
    BLOCKED_BY_CODER = "blocked_by_agent"
    KILLED = "killed"
    PARTIAL = "partial"
    TERMINAL = "terminal"
    # The observer worker woke before its epic's children were all
    # terminal: release the bead at once, count nothing, comment nothing.
    WAITING = "waiting"


@dataclass(frozen=True, slots=True)
class TaskOutcomeRecord:
    """One attempt's outcome plus the detail the policy needs."""

    outcome: TaskOutcome
    exit_code: int | None = None
    reason: str = ""
    resets_at: int | None = None
    stderr_tail: str | None = None
    # Set when RESULT.json declared status=done: the worker's own summary,
    # telling retry_policy to close the bead itself rather than count
    # towards the no-close rounds.
    close_reason: str | None = None


__all__ = [
    "AttemptKind",
    "Event",
    "EventKind",
    "Json",
    "Task",
    "TaskOutcome",
    "TaskOutcomeRecord",
    "TaskStatus",
]
