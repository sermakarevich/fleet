"""Pure "what happens after this task outcome" policy.

No I/O, no logging, no queue calls. ``decide`` takes plain values and
returns a ``Decision`` describing what the caller (``orchestrator/reap.py``)
should do. All side effects live in the caller.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum

from fleet.core.config import RuntimeConfig
from fleet.core.limits import NOCLOSE_LIMIT, RATE_LIMIT_DEFAULT_SLEEP_SEC, RETRY_LIMIT
from fleet.core.task import TaskOutcome, TaskOutcomeRecord


@dataclass
class Counters:
    failures: int
    noclose: int
    stalls: int


class Action(Enum):
    CLOSE = "close"
    RELEASE = "release"
    BLOCK = "block"
    RELEASE_AFTER_RATE_LIMIT = "release_after_rate_limit"
    RELEASE_FOR_CONTEXT = "release_for_context"
    NOOP = "noop"


@dataclass
class Decision:
    action: Action
    reason: str = ""
    sleep_sec: int | None = None
    increment: str | None = None
    needs_validation: bool = False


def decide(
    record: TaskOutcomeRecord,
    counters: Counters,
    bead_status: str | None,
    cfg: RuntimeConfig,
) -> Decision:
    match record.outcome:
        case TaskOutcome.SUCCESS:
            if bead_status != "in_progress":
                return Decision(Action.NOOP, reason="already closed on exit")
            count = counters.noclose + 1
            if count >= NOCLOSE_LIMIT:
                reason = (
                    f"no-close limit exhausted ({count}/{NOCLOSE_LIMIT}); "
                    "needs human review"
                )
                return Decision(Action.BLOCK, reason=reason, increment="noclose")
            reason = f"re-queueing (success without close; #{count}/{NOCLOSE_LIMIT})"
            return Decision(Action.RELEASE, reason=reason, increment="noclose")

        case TaskOutcome.CONTEXT_PRESSURE:
            if bead_status != "in_progress":
                return Decision(Action.NOOP, reason="already closed on exit")
            return Decision(
                Action.RELEASE_FOR_CONTEXT,
                reason="context_pressure; resume on next claim",
            )

        case TaskOutcome.RATE_LIMIT:
            now_ts = datetime.now(tz=UTC).timestamp()
            resets_at = record.resets_at
            sleep_until_ts = max(
                float(resets_at) if resets_at is not None else 0.0,
                now_ts + RATE_LIMIT_DEFAULT_SLEEP_SEC,
            )
            # Round up: reap.py re-anchors this delta to a fresh `now()` taken
            # after decide() returns, so rounding down could undershoot
            # resets_at by up to a second.
            sleep_sec = math.ceil(sleep_until_ts - now_ts)
            reason = (
                f"rate_limit, sleep until {resets_at}"
                if resets_at is not None
                else "rate_limit"
            )
            return Decision(
                Action.RELEASE_AFTER_RATE_LIMIT, reason=reason, sleep_sec=sleep_sec
            )

        case TaskOutcome.BLOCKED_BY_AGENT:
            return Decision(Action.BLOCK, reason="agent set task to blocked")

        case TaskOutcome.KILLED:
            if record.reason == "stalled":
                count = counters.stalls + 1
                if count >= cfg.stall_block_after:
                    reason = (
                        f"stalled {count} times (no output for "
                        f"{cfg.stall_warning_minutes} min each); needs human review"
                    )
                    return Decision(Action.BLOCK, reason=reason, increment="stall")
                reason = (
                    f"stalled (no output for {cfg.stall_warning_minutes} min); "
                    f"killed and re-queued #{count}/{cfg.stall_block_after}"
                )
                return Decision(Action.RELEASE, reason=reason, increment="stall")
            if bead_status != "in_progress":
                return Decision(Action.NOOP, reason="already closed on exit")
            return Decision(Action.BLOCK, reason="manually interrupted")

        case TaskOutcome.FAILURE:
            if bead_status != "in_progress":
                return Decision(Action.NOOP, reason="already closed on exit")
            new_count = counters.failures + 1
            if new_count >= RETRY_LIMIT:
                reason = (
                    f"retry limit ({RETRY_LIMIT}) exhausted; "
                    f"last failure: {record.reason}"
                )
                return Decision(Action.BLOCK, reason=reason, increment="failure")
            reason = f"subprocess failure rc={record.exit_code}; will retry"
            return Decision(Action.RELEASE, reason=reason, increment="failure")

    raise ValueError(f"unhandled outcome: {record.outcome!r}")
