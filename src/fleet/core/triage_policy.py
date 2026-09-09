"""Rule-based triage proposals for blocked tasks. Pure: no I/O.

The supervisor's triage loop (orchestrator/triage.py) calls ``propose`` for
each blocked bead and posts the returned text + options as a non-blocking
ask_human question. ``ignore_active`` is shared by triage, the API summary,
and the CLI's ``--ignored`` listing so "ignored" means one thing everywhere.

``propose`` builds a ``TriageInput`` and returns the first matching row of
``TRIAGE_RULES``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fleet.core.iso import parse_iso
from fleet.core.limits import CONTEXT_MAX_ROUNDS, FAILURE_MAX_ROUNDS, STALL_MAX_ROUNDS
from fleet.core.result import ResultStatus

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


@dataclass(frozen=True)
class TriageInput:
    """Everything one triage rule needs, derived once by ``propose``."""

    task_id: str
    title: str
    header: str
    rounds: dict
    rate_limited: bool
    stderr_tail: str
    result: dict | None
    blocked_reason: str


@dataclass(frozen=True)
class TriageRule:
    """One triage row: name, matches(), proposal(). First match wins."""

    name: str
    matches: Callable[[TriageInput], bool]
    proposal: Callable[[TriageInput], Proposal]


def _is_rate_limited(triage: TriageInput) -> bool:
    """True when recent attempts hit provider rate limits."""
    return triage.rate_limited


def _rate_limit_proposal(triage: TriageInput) -> Proposal:
    """Suggest switching coder/model to route around the exhausted quota."""
    return Proposal(
        text=(
            f"{triage.header}\nRecent attempts hit provider rate limits. "
            "Switching coder/model may route around the exhausted quota."
        ),
        options=[RETRY_SAME, "switch to claude/sonnet", RETRY_OPUS]
        + [o for o in COMMON_OPTIONS if o not in (RETRY_SAME, RETRY_OPUS)],
    )


def _is_stall_exhausted(triage: TriageInput) -> bool:
    """True when stall/timeout rounds hit the retry cap."""
    return triage.rounds.get("stall", 0) >= STALL_MAX_ROUNDS


def _stall_proposal(triage: TriageInput) -> Proposal:
    """Suggest a stronger model for a worker that keeps stalling."""
    return Proposal(
        text=(
            f"{triage.header}\nThe worker stalled/timed out {triage.rounds['stall']} times in a "
            "row. A stronger model may get unstuck faster."
        ),
        options=list(COMMON_OPTIONS),
    )


def _is_context_exhausted(triage: TriageInput) -> bool:
    """True when context-pressure rounds hit the retry cap."""
    return triage.rounds.get("context", 0) >= CONTEXT_MAX_ROUNDS


def _context_proposal(triage: TriageInput) -> Proposal:
    """Explain the task is too large and must be split by hand."""
    return Proposal(
        text=(
            f"{triage.header}\nContext-pressure retries are exhausted "
            f"({triage.rounds['context']}/{CONTEXT_MAX_ROUNDS}); the task is too large "
            "for one worker. Fleet cannot split it automatically — edit the "
            "task text (write the split in the note) and retry, or close it."
        ),
        options=list(COMMON_OPTIONS),
    )


def _is_worker_blocked(triage: TriageInput) -> bool:
    """True when the worker's own RESULT.json declares it blocked."""
    return triage.result is not None and triage.result.get("status") == ResultStatus.BLOCKED.value


def _worker_blocked_proposal(triage: TriageInput) -> Proposal:
    """Quote the worker's report and open questions back to the operator."""
    quoted = triage.result.get("blocked_reason") if triage.result else ""
    questions = triage.result.get("open_questions") if triage.result else []
    lines = [triage.header, f"Worker's report: {quoted or ''}"]
    lines += [f"Open question: {q}" for q in questions or []]
    lines.append("Answer in the note (appended to the task) and retry, or pick another option.")
    return Proposal(text="\n".join(lines), options=list(COMMON_OPTIONS))


def _is_failure_exhausted(triage: TriageInput) -> bool:
    """True when failure rounds hit the retry cap."""
    return triage.rounds.get("failure", 0) >= FAILURE_MAX_ROUNDS


def _failure_proposal(triage: TriageInput) -> Proposal:
    """Show the failure count plus the last output tail, if any."""
    text = (
        f"{triage.header}\nFailure retries are exhausted "
        f"({triage.rounds['failure']}/{FAILURE_MAX_ROUNDS})."
    )
    if triage.stderr_tail:
        text += f"\nLast output tail:\n{triage.stderr_tail}"
    return Proposal(text=text, options=list(COMMON_OPTIONS))


def _is_default(triage: TriageInput) -> bool:
    """Catch-all: always matches so propose() always returns a proposal."""
    return True


def _default_proposal(triage: TriageInput) -> Proposal:
    """Ask the operator how fleet should proceed."""
    return Proposal(
        text=f"{triage.header}\nHow should fleet proceed?",
        options=list(COMMON_OPTIONS),
    )


# Evaluation order is the policy: rate limits first, then stall, context,
# the worker's own blocked report, failure, and finally the default ask.
TRIAGE_RULES: list[TriageRule] = [
    TriageRule("rate_limited", _is_rate_limited, _rate_limit_proposal),
    TriageRule("stall_exhausted", _is_stall_exhausted, _stall_proposal),
    TriageRule("context_exhausted", _is_context_exhausted, _context_proposal),
    TriageRule("worker_blocked", _is_worker_blocked, _worker_blocked_proposal),
    TriageRule("failure_exhausted", _is_failure_exhausted, _failure_proposal),
    TriageRule("default", _is_default, _default_proposal),
]


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
    parsed = parse_iso(ignore_until)
    if parsed is None:
        return False
    ref = now if now is not None else datetime.now(tz=UTC)
    return parsed > ref


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
    triage = TriageInput(
        task_id=task_id,
        title=title,
        header=f"Task {task_id} ({title}) is blocked: {blocked_reason}",
        rounds=rounds,
        rate_limited=bool(attempts.get("rate_limited")),
        stderr_tail=(attempts.get("stderr_tail") or "").strip(),
        result=result,
        blocked_reason=blocked_reason,
    )
    for rule in TRIAGE_RULES:
        if rule.matches(triage):
            return rule.proposal(triage)
    raise ValueError("TRIAGE_RULES has no default rule")


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
