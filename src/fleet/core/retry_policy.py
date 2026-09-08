"""One retry-policy table, readable at a glance. Pure: no I/O.

Rounds per outcome are COUNTED from attempt history (consecutive
same-outcome attempts, reset when an attempt ends differently), so no
counter files are needed. Callers pass ``history =
state.attempts.load_attempts(task_dir)`` (prior attempts; the current
attempt has a start line but no end line yet).
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum

from fleet.core.config import RuntimeConfig
from fleet.core.limits import RATE_LIMIT_DEFAULT_SLEEP_SEC
from fleet.core.task import TaskOutcome, TaskOutcomeRecord

# Retry table. "max rounds" counts the current attempt too: round n means
# this outcome has ended n times in a row (trailing streak in history + 1).
FAILURE_MAX_ROUNDS = 3
FAILURE_WAIT_SEC = (60, 300, 900)
FAILURE_JITTER_SEC = 30
STALL_MAX_ROUNDS = 2
CONTEXT_MAX_ROUNDS = 3
PARTIAL_MAX_ROUNDS = 5
NOCLOSE_MAX_ROUNDS = 3


class Action(Enum):
    CLOSE = "close"
    RELEASE = "release"
    BLOCK = "block"
    NOOP = "noop"


@dataclass
class Decision:
    action: Action
    reason: str = ""
    # Seconds the caller should wait before the task becomes claimable
    # again. Only meaningful for RELEASE (reap stores it as task.json
    # `retry_after`; claim_next skips tasks whose retry_after is in the
    # future). None/0 means "right away".
    wait_sec: int | None = None


def _category_of(
    outcome: str | None,
    reason: str | None,
    close_reason: bool = False,
    action: str | None = None,
) -> str | None:
    """Map a history entry (or the current record) to a rounds category.

    Categories: "failure", "stall", "context", "partial", "noclose".
    RATE_LIMIT is deliberately not counted (unlimited retries).
    Returns None for entries that break every streak (running attempts,
    terminal outcomes, manual kills, closes).
    """
    if outcome == TaskOutcome.FAILURE.value:
        return "failure"
    if outcome == TaskOutcome.CONTEXT_PRESSURE.value:
        return "context"
    if outcome == TaskOutcome.PARTIAL.value:
        return "partial"
    if outcome == TaskOutcome.KILLED.value:
        if reason in ("stalled", "timeout"):
            return "stall"
        return None
    if outcome == TaskOutcome.SUCCESS.value:
        # SUCCESS that closed the bead is not a round: it ends the streak.
        # History rows don't carry close_reason, but reap journals the
        # Decision action ("close") on every end line, so use that.
        if close_reason or action in ("close", "closed"):
            return None
        return "noclose"
    return None


def _trailing_streak(history: list[dict], category: str) -> int:
    """Count trailing consecutive attempts in *category*, oldest→newest history.

    Rows with ``kind == "compact"`` (the compaction job, which journals its
    own attempt row for visibility) never count toward — or break — a streak:
    they are skipped, since they are not worker outcomes.
    """
    count = 0
    for entry in reversed(history):
        if not isinstance(entry, dict):
            break
        if entry.get("kind") == "compact":
            continue
        if entry.get("outcome") is None:
            # Attempt started but never ended: ignore it, keep scanning back.
            continue
        cat = _category_of(entry.get("outcome"), entry.get("reason"), action=entry.get("action"))
        if cat == category:
            count += 1
        else:
            break
    return count


def rounds_for_history(history: list[dict]) -> dict[str, int]:
    """Return trailing-streak rounds per category for UI/API summaries."""
    return {
        "failure": _trailing_streak(history, "failure"),
        "stall": _trailing_streak(history, "stall"),
        "context": _trailing_streak(history, "context"),
        "partial": _trailing_streak(history, "partial"),
        "noclose": _trailing_streak(history, "noclose"),
    }


def _failure_wait(rounds: int) -> int:
    base = FAILURE_WAIT_SEC[min(max(rounds, 1) - 1, len(FAILURE_WAIT_SEC) - 1)]
    return base + random.randint(0, FAILURE_JITTER_SEC)


def _rate_limit_wait(resets_at: int | None) -> int:
    now_ts = datetime.now(tz=UTC).timestamp()
    sleep_until_ts = max(
        float(resets_at) if resets_at is not None else 0.0,
        now_ts + RATE_LIMIT_DEFAULT_SLEEP_SEC,
    )
    # Round up: the caller re-anchors this delta to a fresh now(), so
    # rounding down could undershoot resets_at by up to a second.
    base = math.ceil(sleep_until_ts - now_ts)
    return max(base, RATE_LIMIT_DEFAULT_SLEEP_SEC)


def decide(
    record: TaskOutcomeRecord,
    history: list[dict],
    bead_status: str | None,
    cfg: RuntimeConfig,
) -> Decision:
    """Apply the retry table to *record* given prior *history*."""
    match record.outcome:
        case TaskOutcome.TERMINAL:
            return Decision(Action.BLOCK, reason=record.reason or "terminal setup error")

        case TaskOutcome.BLOCKED_BY_AGENT:
            return Decision(
                Action.BLOCK, reason=record.reason or "agent set task to blocked"
            )

        case TaskOutcome.SUCCESS:
            if bead_status != "in_progress":
                return Decision(Action.NOOP, reason="already closed on exit")
            if record.close_reason is not None:
                return Decision(Action.CLOSE, reason=record.close_reason)
            rounds = _trailing_streak(history, "noclose") + 1
            if rounds >= NOCLOSE_MAX_ROUNDS:
                return Decision(
                    Action.BLOCK,
                    reason=(
                        f"no-close limit exhausted ({rounds}/{NOCLOSE_MAX_ROUNDS}); "
                        "needs human review"
                    ),
                )
            return Decision(
                Action.RELEASE,
                reason=f"re-queueing (success without close; #{rounds}/{NOCLOSE_MAX_ROUNDS})",
                wait_sec=0,
            )

        case TaskOutcome.PARTIAL:
            if bead_status != "in_progress":
                return Decision(Action.NOOP, reason="already closed on exit")
            rounds = _trailing_streak(history, "partial") + 1
            if rounds >= PARTIAL_MAX_ROUNDS:
                return Decision(
                    Action.BLOCK,
                    reason=(
                        f"partial limit exhausted ({rounds}/{PARTIAL_MAX_ROUNDS}); "
                        "needs human review"
                    ),
                )
            reason = record.reason or f"partial progress; re-queueing (#{rounds}/{PARTIAL_MAX_ROUNDS})"
            return Decision(Action.RELEASE, reason=reason, wait_sec=0)

        case TaskOutcome.CONTEXT_PRESSURE:
            if bead_status != "in_progress":
                return Decision(Action.NOOP, reason="already closed on exit")
            rounds = _trailing_streak(history, "context") + 1
            if rounds >= CONTEXT_MAX_ROUNDS:
                return Decision(
                    Action.BLOCK,
                    reason="too large for one worker; split it",
                )
            return Decision(
                Action.RELEASE,
                reason="context_pressure; resume on next claim",
                wait_sec=0,
            )

        case TaskOutcome.RATE_LIMIT:
            return Decision(
                Action.RELEASE,
                reason=(
                    f"rate_limit, sleep until {record.resets_at}"
                    if record.resets_at is not None
                    else "rate_limit"
                ),
                wait_sec=_rate_limit_wait(record.resets_at),
            )

        case TaskOutcome.KILLED:
            if record.reason in ("stalled", "timeout"):
                rounds = _trailing_streak(history, "stall") + 1
                if rounds >= STALL_MAX_ROUNDS:
                    return Decision(
                        Action.BLOCK,
                        reason=(
                            f"stalled {rounds} times; needs human review"
                        ),
                    )
                return Decision(
                    Action.RELEASE,
                    reason=f"stalled; killed and re-queued #{rounds}/{STALL_MAX_ROUNDS}",
                    wait_sec=0,
                )
            if bead_status != "in_progress":
                return Decision(Action.NOOP, reason="already closed on exit")
            return Decision(Action.BLOCK, reason="manually interrupted")

        case TaskOutcome.FAILURE:
            if bead_status != "in_progress":
                return Decision(Action.NOOP, reason="already closed on exit")
            rounds = _trailing_streak(history, "failure") + 1
            if rounds >= FAILURE_MAX_ROUNDS:
                return Decision(
                    Action.BLOCK,
                    reason=(
                        f"retry limit ({FAILURE_MAX_ROUNDS}) exhausted; "
                        f"last failure: {record.reason}"
                    ),
                )
            return Decision(
                Action.RELEASE,
                reason=f"subprocess failure rc={record.exit_code}; will retry",
                wait_sec=_failure_wait(rounds),
            )

    raise ValueError(f"unhandled outcome: {record.outcome!r}")
