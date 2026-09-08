"""Rule-based triage proposals for blocked tasks. Pure: no I/O.

The supervisor's triage loop (orchestrator/triage.py) calls ``propose`` for
each blocked bead and posts the returned text + options as a non-blocking
ask_human question. ``ignore_active`` is shared by triage, the API summary,
and the CLI's ``--ignored`` listing so "ignored" means one thing everywhere.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fleet.core.retry_policy import CONTEXT_MAX_ROUNDS, FAILURE_MAX_ROUNDS, STALL_MAX_ROUNDS

# Canonical answer options. The apply step (orchestrator/triage.py) matches
# the operator's selected answer against these strings verbatim.
RETRY_SAME = "retry same setup"
RETRY_OPUS = "retry with claude/opus"
EDIT_RETRY = "edit task text and retry (write in note)"
CLOSE = "close as won't do"
IGNORE_24H = "ignore 24h"
IGNORE_FOREVER = "ignore forever"

COMMON_OPTIONS = [RETRY_SAME, RETRY_OPUS, EDIT_RETRY, CLOSE, IGNORE_24H, IGNORE_FOREVER]

# Options for the digest question asked when too many tasks block at once.
DIGEST_IGNORE_ALL = "ignore all 24h"
DIGEST_LEAVE = "leave for later"
DIGEST_OPTIONS = [DIGEST_IGNORE_ALL, DIGEST_LEAVE]

#: Max per-task triage questions posted in a single tick; extra candidates
#: are folded into one digest question.
MAX_PER_TASK_QUESTIONS = 5


@dataclass
class Proposal:
    """Question text + answer options for one blocked task."""

    text: str
    options: list[str]


def ignore_active(ignore_until: str | None, now: datetime | None = None) -> bool:
    """True when an ``ignore_until`` value still suppresses triage.

    ``"forever"`` never expires; otherwise the value is an ISO timestamp and
    is active while it lies in the future. Missing, empty, or unparsable
    values are inactive (fail open: triage still asks).
    """
    if not ignore_until or not isinstance(ignore_until, str):
        return False
    if ignore_until.strip().lower() == "forever":
        return True
    try:
        dt = datetime.fromisoformat(ignore_until)
    except (ValueError, TypeError):
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    ref = now if now is not None else datetime.now(tz=UTC)
    return dt > ref


def ignore_until_24h(now: datetime | None = None) -> str:
    """ISO timestamp 24h in the future, for the "ignore 24h" answer."""
    ref = now if now is not None else datetime.now(tz=UTC)
    return (ref + timedelta(hours=24)).isoformat()


def propose(
    task: dict,
    attempts: dict,
    result: dict | None,
    blocked_reason: str,
) -> Proposal:
    """Build a triage proposal for one blocked task.

    *task*: task.json content (uses ``id`` and ``title``).
    *attempts*: ``{"rounds": {"failure": n, "stall": n, "context": n, ...},
    "rate_limited": bool, "stderr_tail": str | None}``.
    *result*: parsed task-level RESULT.json (``status`` / ``blocked_reason`` /
    ``open_questions`` keys) or None when absent.
    *blocked_reason*: the fleet block reason from task.json.
    """
    task_id = task.get("id", "?")
    title = task.get("title", "")
    rounds = attempts.get("rounds") or {}
    header = f"Task {task_id} ({title}) is blocked: {blocked_reason}"

    if attempts.get("rate_limited"):
        return Proposal(
            text=(
                f"{header}\nRecent attempts hit provider rate limits. "
                "Switching coder/model may route around the exhausted quota."
            ),
            options=[RETRY_SAME, "switch to claude/sonnet", RETRY_OPUS]
            + [o for o in COMMON_OPTIONS if o not in (RETRY_SAME, RETRY_OPUS)],
        )
    if rounds.get("stall", 0) >= STALL_MAX_ROUNDS:
        return Proposal(
            text=(
                f"{header}\nThe worker stalled/timed out {rounds['stall']} times in a "
                "row. A stronger model may get unstuck faster."
            ),
            options=list(COMMON_OPTIONS),
        )
    if rounds.get("context", 0) >= CONTEXT_MAX_ROUNDS:
        return Proposal(
            text=(
                f"{header}\nContext-pressure retries are exhausted "
                f"({rounds['context']}/{CONTEXT_MAX_ROUNDS}); the task is too large "
                "for one worker. Fleet cannot split it automatically — edit the "
                "task text (write the split in the note) and retry, or close it."
            ),
            options=list(COMMON_OPTIONS),
        )
    if result is not None and result.get("status") == "blocked":
        quoted = result.get("blocked_reason") or ""
        questions = result.get("open_questions") or []
        lines = [header, f"Worker's report: {quoted}"]
        lines += [f"Open question: {q}" for q in questions]
        lines.append(
            "Answer in the note (appended to the task) and retry, or pick another option."
        )
        return Proposal(text="\n".join(lines), options=list(COMMON_OPTIONS))
    if rounds.get("failure", 0) >= FAILURE_MAX_ROUNDS:
        tail = (attempts.get("stderr_tail") or "").strip()
        text = (
            f"{header}\nFailure retries are exhausted "
            f"({rounds['failure']}/{FAILURE_MAX_ROUNDS})."
        )
        if tail:
            text += f"\nLast output tail:\n{tail}"
        return Proposal(text=text, options=list(COMMON_OPTIONS))
    return Proposal(
        text=f"{header}\nHow should fleet proceed?",
        options=list(COMMON_OPTIONS),
    )


def digest_text(candidates: list[dict]) -> str:
    """One digest question listing blocked tasks beyond the per-task budget."""
    lines = [
        f"{len(candidates)} tasks blocked at once; per-task questions were "
        "asked for the first "
        f"{MAX_PER_TASK_QUESTIONS}. The rest need a decision:",
    ]
    for cand in candidates:
        lines.append(
            f"- {cand.get('id')}: {cand.get('title', '')} — {cand.get('blocked_reason', '')}"
        )
    return "\n".join(lines)
