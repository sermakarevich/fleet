"""Retry policy as a data table. Pure: no I/O.

Rounds per outcome are COUNTED from attempt history (consecutive
same-outcome attempts, reset when an attempt ends differently), so no
counter files are needed. Callers pass ``history =
state.attempts.load_attempts(task_dir)`` (prior attempts; the current
attempt has a start line but no end line yet).

``decide`` finds the first row of ``RETRY_TABLE`` matching the current
record and applies it. Round caps live in ``core/limits.py``.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum

from fleet.core.config import RuntimeConfig
from fleet.core.limits import (
    CONTEXT_MAX_ROUNDS,
    FAILURE_MAX_ROUNDS,
    NOCLOSE_MAX_ROUNDS,
    PARTIAL_MAX_ROUNDS,
    RATE_LIMIT_DEFAULT_SLEEP_SEC,
    STALL_MAX_ROUNDS,
)
from fleet.core.task import TaskOutcome, TaskOutcomeRecord

# A FAILURE carrying this reason is not the worker's fault: the supervisor
# stopped (restart, deploy). It is re-queued at once and never counts as a
# round, nor breaks a streak, so a redeploy cannot push a task into BLOCK.
SHUTDOWN_REASON = "supervisor_shutdown"
FAILURE_WAIT_SEC = (60, 300, 900)
FAILURE_JITTER_SEC = 30
# WAITING releases carry a short delay so a not-yet-ready epic does not
# hot-loop through claim (still no bead comment, no round counting).
WAITING_WAIT_SEC = 60


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


# How a rule matches a record's reason: None matches any reason, a string
# matches it exactly, a tuple matches membership, a callable is a predicate
# over the whole record (for fields like close_reason or resets_at).
ReasonMatch = str | tuple[str, ...] | Callable[[TaskOutcomeRecord], bool] | None


@dataclass(frozen=True)
class RetryRule:
    """One row of the retry table, evaluated top to bottom, first match wins."""

    outcome: TaskOutcome | None
    reason_match: ReasonMatch = None
    max_rounds: int | None = None
    action: Action = Action.RELEASE
    block_reason_tmpl: str = ""
    # Extra knobs the five core fields cannot express:
    # release_reason_tmpl renders the RELEASE/NOOP/CLOSE reason, wait_for
    # computes RELEASE wait_sec from (record, rounds), bead_open restricts
    # the row to open (True) or already-closed (False) beads, and
    # default_reason fills {reason} when the record carries none.
    release_reason_tmpl: str = ""
    wait_for: Callable[[TaskOutcomeRecord, int], int | None] | None = None
    bead_open: bool | None = None
    default_reason: str = ""


def _has_close_reason(record: TaskOutcomeRecord) -> bool:
    """True when the worker reported done and asked to close the bead."""
    return record.close_reason is not None


def _no_close_reason(record: TaskOutcomeRecord) -> bool:
    """True when a SUCCESS carries no close request (counts as a no-close round)."""
    return record.close_reason is None


def _is_stall_reason(record: TaskOutcomeRecord) -> bool:
    """True when a KILLED record means stalled/timed-out (shares one ladder)."""
    return record.reason in ("stalled", "timeout")


def _not_stall_reason(record: TaskOutcomeRecord) -> bool:
    """True when a KILLED record is a manual interrupt, not a stall."""
    return record.reason not in ("stalled", "timeout")


def _has_reason(record: TaskOutcomeRecord) -> bool:
    """True when the record carries its own release reason text."""
    return bool(record.reason)


def _no_reason(record: TaskOutcomeRecord) -> bool:
    """True when the release reason must fall back to the round counter text."""
    return not record.reason


def _has_resets_at(record: TaskOutcomeRecord) -> bool:
    """True when a rate-limit record names the quota reset timestamp."""
    return record.resets_at is not None


def _no_resets_at(record: TaskOutcomeRecord) -> bool:
    """True when a rate-limit record names no reset timestamp."""
    return record.resets_at is None


def _wait_const(n: int) -> Callable[[TaskOutcomeRecord, int], int | None]:
    """Build a wait_for returning a fixed delay."""
    return lambda _record, _rounds: n


# Evaluation order is the policy: terminal states first, then the
# any-bead releases (stall, rate limit, waiting, shutdown), then the
# closed-bead catch-all, then the open-bead streak ladders.
RETRY_TABLE: list[RetryRule] = [
    RetryRule(
        TaskOutcome.TERMINAL,
        action=Action.BLOCK,
        block_reason_tmpl="{reason}",
        default_reason="terminal setup error",
    ),
    RetryRule(
        TaskOutcome.BLOCKED_BY_AGENT,
        action=Action.BLOCK,
        block_reason_tmpl="{reason}",
        default_reason="agent set task to blocked",
    ),
    RetryRule(
        TaskOutcome.KILLED,
        reason_match=("stalled", "timeout"),
        max_rounds=STALL_MAX_ROUNDS,
        action=Action.RELEASE,
        block_reason_tmpl="stalled {rounds} times; needs human review",
        release_reason_tmpl="stalled; killed and re-queued #{rounds}/{max}",
        wait_for=_wait_const(0),
    ),
    RetryRule(
        TaskOutcome.RATE_LIMIT,
        reason_match=_has_resets_at,
        action=Action.RELEASE,
        release_reason_tmpl="rate_limit, sleep until {resets_at}",
        wait_for=lambda record, _rounds: _rate_limit_wait(record.resets_at),
    ),
    RetryRule(
        TaskOutcome.RATE_LIMIT,
        reason_match=_no_resets_at,
        action=Action.RELEASE,
        release_reason_tmpl="rate_limit",
        wait_for=lambda record, _rounds: _rate_limit_wait(record.resets_at),
    ),
    RetryRule(
        TaskOutcome.WAITING,
        action=Action.RELEASE,
        release_reason_tmpl="{reason}",
        default_reason="waiting on child beads",
        wait_for=_wait_const(WAITING_WAIT_SEC),
    ),
    RetryRule(
        TaskOutcome.FAILURE,
        reason_match=SHUTDOWN_REASON,
        bead_open=True,
        action=Action.RELEASE,
        release_reason_tmpl="supervisor shutdown; re-queued",
        wait_for=_wait_const(0),
    ),
    RetryRule(
        None,
        bead_open=False,
        action=Action.NOOP,
        release_reason_tmpl="already closed on exit",
    ),
    RetryRule(
        TaskOutcome.SUCCESS,
        reason_match=_has_close_reason,
        bead_open=True,
        action=Action.CLOSE,
        release_reason_tmpl="{close_reason}",
    ),
    RetryRule(
        TaskOutcome.SUCCESS,
        reason_match=_no_close_reason,
        max_rounds=NOCLOSE_MAX_ROUNDS,
        bead_open=True,
        action=Action.RELEASE,
        block_reason_tmpl="no-close limit exhausted ({rounds}/{max}); needs human review",
        release_reason_tmpl="re-queueing (success without close; #{rounds}/{max})",
        wait_for=_wait_const(0),
    ),
    RetryRule(
        TaskOutcome.PARTIAL,
        reason_match=_has_reason,
        max_rounds=PARTIAL_MAX_ROUNDS,
        bead_open=True,
        action=Action.RELEASE,
        block_reason_tmpl="partial limit exhausted ({rounds}/{max}); needs human review",
        release_reason_tmpl="{reason}",
        wait_for=_wait_const(0),
    ),
    RetryRule(
        TaskOutcome.PARTIAL,
        reason_match=_no_reason,
        max_rounds=PARTIAL_MAX_ROUNDS,
        bead_open=True,
        action=Action.RELEASE,
        block_reason_tmpl="partial limit exhausted ({rounds}/{max}); needs human review",
        release_reason_tmpl="partial progress; re-queueing (#{rounds}/{max})",
        wait_for=_wait_const(0),
    ),
    RetryRule(
        TaskOutcome.CONTEXT_PRESSURE,
        max_rounds=CONTEXT_MAX_ROUNDS,
        bead_open=True,
        action=Action.RELEASE,
        block_reason_tmpl="too large for one worker; split it",
        release_reason_tmpl="context_pressure; resume on next claim",
        wait_for=_wait_const(0),
    ),
    RetryRule(
        TaskOutcome.KILLED,
        reason_match=_not_stall_reason,
        bead_open=True,
        action=Action.BLOCK,
        block_reason_tmpl="manually interrupted",
    ),
    RetryRule(
        TaskOutcome.FAILURE,
        max_rounds=FAILURE_MAX_ROUNDS,
        bead_open=True,
        action=Action.RELEASE,
        block_reason_tmpl="retry limit ({max}) exhausted; last failure: {reason}",
        release_reason_tmpl="subprocess failure rc={exit_code}; will retry",
        wait_for=lambda _record, rounds: _failure_wait(rounds),
    ),
]


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
    terminal outcomes, manual kills, closes, and the "unblocked" row an
    operator's unblock appends so old failures stop counting).
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
        if entry.get("reason") == SHUTDOWN_REASON:
            # Supervisor restart, not a worker outcome: neither counts nor breaks.
            continue
        if entry.get("outcome") == TaskOutcome.WAITING.value:
            # The observer woke early: neither a round nor a streak break.
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


def streak_of(history: list[dict], outcome: TaskOutcome, reason: str) -> int:
    """Count the trailing streak in history for the current record's category."""
    category = _category_of(outcome.value if isinstance(outcome, TaskOutcome) else outcome, reason)
    if category is None:
        return 0
    return _trailing_streak(history, category)


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


def _reason_matches(match: ReasonMatch, record: TaskOutcomeRecord) -> bool:
    """True when *record* satisfies a rule's reason_match clause."""
    if match is None:
        return True
    if callable(match):
        return bool(match(record))
    if isinstance(match, str):
        return record.reason == match
    return record.reason in match


def _rule_matches(rule: RetryRule, record: TaskOutcomeRecord, bead_status: str | None) -> bool:
    """True when *rule* is a candidate for *record* on a bead with *bead_status*."""
    if rule.outcome is not None and record.outcome != rule.outcome:
        return False
    if rule.bead_open is True and bead_status != "in_progress":
        return False
    if rule.bead_open is False and bead_status == "in_progress":
        return False
    return _reason_matches(rule.reason_match, record)


def _render(tmpl: str, rule: RetryRule, record: TaskOutcomeRecord, rounds: int) -> str:
    """Fill a reason template from the rule, record, and current round."""
    return tmpl.format(
        reason=record.reason or rule.default_reason,
        rounds=rounds,
        max=rule.max_rounds,
        exit_code=record.exit_code,
        resets_at=record.resets_at,
        close_reason=record.close_reason,
    )


def _apply_rule(rule: RetryRule, record: TaskOutcomeRecord, history: list[dict]) -> Decision:
    """Turn the first matching rule into a Decision, counting rounds once."""
    if rule.max_rounds is None:
        if rule.action is Action.BLOCK:
            return Decision(Action.BLOCK, reason=_render(rule.block_reason_tmpl, rule, record, 0))
        wait = rule.wait_for(record, 0) if rule.wait_for is not None else None
        return Decision(
            rule.action, reason=_render(rule.release_reason_tmpl, rule, record, 0), wait_sec=wait
        )
    rounds = streak_of(history, record.outcome, record.reason) + 1
    if rounds >= rule.max_rounds:
        return Decision(Action.BLOCK, reason=_render(rule.block_reason_tmpl, rule, record, rounds))
    wait = rule.wait_for(record, rounds) if rule.wait_for is not None else None
    return Decision(
        Action.RELEASE,
        reason=_render(rule.release_reason_tmpl, rule, record, rounds),
        wait_sec=wait,
    )


def decide(
    record: TaskOutcomeRecord,
    history: list[dict],
    bead_status: str | None,
    cfg: RuntimeConfig,
) -> Decision:
    """Apply the first matching RETRY_TABLE row to *record* given *history*."""
    for rule in RETRY_TABLE:
        if _rule_matches(rule, record, bead_status):
            return _apply_rule(rule, record, history)
    raise ValueError(f"unhandled outcome: {record.outcome!r}")
