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
RESOLVE_MERGE = "resolve merge conflict with a worker"
EDIT_RETRY = "edit task text and retry (write in note)"
CLOSE = "close as won't do"
IGNORE_24H = "ignore 24h"
IGNORE_FOREVER = "ignore forever"

COMMON_OPTIONS = [RETRY_SAME, RETRY_OPUS, EDIT_RETRY, CLOSE, IGNORE_24H, IGNORE_FOREVER]

# First option when a merge-conflict block already has a live repair worker.
REPAIR_RUNNING_PREFIX = "repair worker "

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
class MergeConflictInfo:
    """Where a merge-conflict block strands its branch, parsed from task.json."""

    repo_root: str
    base_ref: str
    branch: str
    files: tuple[str, ...] = ()
    repair_task_id: str | None = None


def merge_conflict_info(meta: dict) -> MergeConflictInfo | None:
    """Parse MergeConflictInfo from a task.json dict; None when never recorded.

    Tolerates missing fields (empty strings, no files) so a half-written
    record still proposes the repair worker instead of falling to default.
    """
    raw = meta.get("merge_conflict")
    if not isinstance(raw, dict):
        return None
    files = raw.get("files")
    paths = tuple(f for f in files if isinstance(f, str) and f) if isinstance(files, list) else ()
    repair = meta.get("repair_task_id")
    return MergeConflictInfo(
        repo_root=raw.get("repo_root") or "",
        base_ref=raw.get("base_ref") or "",
        branch=raw.get("branch") or "",
        files=paths,
        repair_task_id=repair if isinstance(repair, str) and repair else None,
    )


def repair_running_label(repair_task_id: str) -> str:
    """Option text shown while a repair worker for this block is still live."""
    return f"{REPAIR_RUNNING_PREFIX}{repair_task_id} is running"


def is_repair_answer(answer: str | None) -> bool:
    """True when the answer picks the merge-repair path (or its running label)."""
    return answer == RESOLVE_MERGE or (
        isinstance(answer, str) and answer.startswith(REPAIR_RUNNING_PREFIX)
    )


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
    merge_conflict: MergeConflictInfo | None = None


@dataclass(frozen=True)
class TriageRule:
    """One triage row: name, matches(), proposal(). First match wins."""

    name: str
    matches: Callable[[TriageInput], bool]
    proposal: Callable[[TriageInput], Proposal]


def _is_merge_conflict(triage: TriageInput) -> bool:
    """True when the block reason is a failed validation merge into the base."""
    return triage.blocked_reason.startswith("merge conflict into")


def _merge_conflict_proposal(triage: TriageInput) -> Proposal:
    """Offer a repair worker that owns the conflicted branch end to end."""
    info = triage.merge_conflict
    branch = (info.branch if info and info.branch else f"fleet/{triage.task_id}").strip()
    base = (info.base_ref if info and info.base_ref else _merge_base(triage.blocked_reason)).strip()
    files = ", ".join(info.files) if info and info.files else "unknown"
    first = RESOLVE_MERGE
    if info and info.repair_task_id:
        first = repair_running_label(info.repair_task_id)
    return Proposal(
        text=(
            f"{triage.header}\nThe worker finished but its branch `{branch}` no longer merges "
            f"into `{base}` cleanly (files: {files}). A repair worker can merge {base} into "
            f"the branch, resolve the conflicts, run the project checks, fast-forward {base}, "
            "and close this task."
        ),
        options=[first, RETRY_SAME, RETRY_OPUS, CLOSE, IGNORE_24H, IGNORE_FOREVER],
    )


def _merge_base(blocked_reason: str) -> str:
    """Base ref parsed from a merge-conflict block reason, else a generic label."""
    head, _, _ = blocked_reason.partition(";")
    ref = head.removeprefix("merge conflict into").strip()
    return ref or "the base branch"


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


# Evaluation order is the policy: merge conflicts first (a fresh retry can
# never fix a stranded branch), then rate limits, stall, context, the
# worker's own blocked report, failure, and finally the default ask.
TRIAGE_RULES: list[TriageRule] = [
    TriageRule("merge_conflict", _is_merge_conflict, _merge_conflict_proposal),
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
        merge_conflict=merge_conflict_info(task),
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
