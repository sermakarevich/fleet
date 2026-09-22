"""Supervisor triage loop over blocked beads.

Blocked tasks pile up silently; this scheduled service (every
``config.triage_interval_minutes``; 0 disables) posts one non-blocking
ask_human question per blocked bead with a rule-based fix proposal (see
core/triage_policy.py) and applies the operator's answer on the next
tick.

A question is held while the blocked-task investigator is still working,
bounded by ``triage_investigation_wait_minutes``: when a blocked_task
trigger already opened an investigation bead but its INVESTIGATION.md has
not landed yet, triage waits instead of asking blind, then folds the
report into the question.

Applied answers change bead state (release/close/ignore), so an
already-applied question no longer matches its bead's live blocked state
and is skipped naturally — no consumed-markers needed.
"""

from __future__ import annotations

import json
import shlex
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

from fleet.beads.queue import Queue
from fleet.core import triage_policy
from fleet.core.effective import effective_coder_model
from fleet.core.errors import FleetError
from fleet.core.investigation import InvestigationReport, parse_report
from fleet.core.iso import parse_iso
from fleet.core.limits import STATUS_LOG_INTERVAL_SEC
from fleet.core.retry_policy import rounds_for_history
from fleet.core.task import TaskOutcome, TaskStatus
from fleet.core.triage_policy import (
    CLOSE,
    DIGEST_IGNORE_ALL,
    EDIT_RETRY,
    IGNORE_24H,
    IGNORE_FOREVER,
    MAX_PER_TASK_QUESTIONS,
    RETRY_OPUS,
    RETRY_SAME,
    is_repair_answer,
)
from fleet.orchestrator.service import ServiceOrder, run_periodic
from fleet.state import attempts as attempts_mod
from fleet.state import paths as state_paths
from fleet.state.attempt_summary import render_markdown, summarize
from fleet.state.attempts import latest_attempt_dir
from fleet.state.investigation import read_report
from fleet.state.task_meta import TaskMeta
from fleet.state.task_summary import read_declared_result
from fleet.triggers.lookup import investigation_task_id
from fleet.triggers.store import TriggerStore

if TYPE_CHECKING:
    from fleet.core.config import RuntimeConfig
    from fleet.integrations.ask_human.store import Question, QuestionStore

    from .state import SupervisorState


class TriageApplyOutcome(StrEnum):
    """What applying one answered triage question did."""

    SKIPPED = "skipped"
    CLOSED = "closed"
    IGNORED = "ignored"
    RELEASED_OPUS = "released-opus"
    RELEASED = "released"
    IGNORED_ALL = "ignored-all"
    REPAIR_SPAWNED = "repair-spawned"


# How many of the newest attempts count for "rate-limit history".
_RATE_LIMIT_WINDOW = 5
# Characters of the derived attempt-summary tail shown for exhausted failure rounds.
_STDERR_TAIL_CHARS = 1500


def _read_meta(fleet_home: Path, task_id: str) -> dict:
    """Read task.json; {} when missing or unparsable."""
    try:
        data = json.loads((state_paths.task_dir(fleet_home, task_id) / "task.json").read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _stderr_tail(task_dir: Path) -> str | None:
    """Tail of the latest attempt's derived summary, if any."""
    attempt_dir = latest_attempt_dir(task_dir)
    if attempt_dir is None:
        return None
    try:
        n = int(attempt_dir.name)
    except ValueError:
        return None
    try:
        text = render_markdown(summarize(task_dir, n))
    except (OSError, ValueError):
        return None
    tail = text.strip()[-_STDERR_TAIL_CHARS:]
    return tail or None


def _investigation_of(
    fleet_home: Path, trigger_store: TriggerStore, task_id: str, blocked_at: str | None
) -> tuple[str | None, InvestigationReport | None, str]:
    """(investigation bead id, parsed report, report path) for one block.

    The bead id is present as soon as the trigger fired; the report and path
    stay None/"" until that investigator worker finished writing it.
    """
    inv_id = investigation_task_id(trigger_store, task_id, blocked_at)
    if inv_id is None:
        return (None, None, "")
    found = read_report(state_paths.task_dir(fleet_home, inv_id))
    if found is None:
        return (inv_id, None, "")
    text, path = found
    return (inv_id, parse_report(text), str(path))


def collect_candidates(
    queue: Queue,
    fleet_home: Path,
    store: QuestionStore,
    limit: int = 100,
    trigger_store: TriggerStore | None = None,
) -> list[dict]:
    """Blocked beads that need a triage question.

    Skipped: beads without task.json ``blocked_reason`` (human-blocked, not
    fleet-blocked), tasks with an active ``ignore_until``, and tasks with a
    triage question already pending for their current ``blocked_at``. A
    cancelled question also suppresses re-asking for the same ``blocked_at``
    ("stop asking me this"); a new ``blocked_at`` asks fresh.
    """
    candidates: list[dict] = []
    trigger_store = trigger_store or TriggerStore(fleet_home)
    try:
        blocked = queue.list_blocked(limit=limit)
    except Exception:
        return []
    for bead in blocked:
        task_id = bead.id
        meta = _read_meta(fleet_home, task_id)
        blocked_reason = meta.get("blocked_reason")
        if not blocked_reason:
            continue
        if triage_policy.ignore_active(meta.get("ignore_until")):
            continue
        blocked_at = meta.get("blocked_at")
        if store.has_suppression_for_task(task_id, blocked_at):
            continue
        task_dir = state_paths.task_dir(fleet_home, task_id)
        history = attempts_mod.load_attempts(task_dir)
        rounds = rounds_for_history(history)
        rate_limited = any(
            h.get("outcome") == TaskOutcome.RATE_LIMIT.value for h in history[-_RATE_LIMIT_WINDOW:]
        )
        inv_id, report, report_path = _investigation_of(
            fleet_home, trigger_store, task_id, blocked_at
        )
        candidates.append(
            {
                "id": task_id,
                "title": meta.get("title", bead.title),
                "description": meta.get("description"),
                "blocked_reason": blocked_reason,
                "blocked_at": blocked_at,
                "attempts": {
                    "rounds": rounds,
                    "rate_limited": rate_limited,
                    "stderr_tail": _stderr_tail(task_dir),
                },
                "result": read_declared_result(task_dir),
                "meta": _live_meta(queue, meta),
                "investigation_task_id": inv_id,
                "investigation": report,
                "investigation_path": report_path,
            }
        )
    return candidates


def waiting_for_investigation(cand: dict, config: RuntimeConfig, now: datetime) -> bool:
    """True when triage should hold this question until the report lands."""
    if not config.triage_wait_for_investigation:
        return False
    if cand["investigation"] is not None:
        return False
    if cand["investigation_task_id"] is None:
        return False
    blocked_at = parse_iso(cand["blocked_at"])
    if blocked_at is None:
        return False
    return now - blocked_at < timedelta(minutes=config.triage_investigation_wait_minutes)


def _append_note_to_description(queue: Queue, fleet_home: Path, task_id: str, note: str) -> None:
    """Append the operator's note as a paragraph to the bead description."""
    current = _read_meta(fleet_home, task_id).get("description") or ""
    updated = f"{current}\n\nOperator note: {note}" if current else f"Operator note: {note}"
    queue.set_bd_fields(task_id, {"description": updated})


_MERGE_REPAIR_TEMPLATE = Path(__file__).resolve().parent.parent / "templates" / "MERGE_REPAIR.md"


def _render_repair_description(info: triage_policy.MergeConflictInfo, task_id: str) -> str:
    """Render MERGE_REPAIR.md for one stranded branch (str.format, like prompts)."""
    files = ", ".join(info.files) if info.files else "unknown"
    return _MERGE_REPAIR_TEMPLATE.read_text(encoding="utf-8").format(
        branch=info.branch,
        repo_root=info.repo_root,
        base_ref=info.base_ref,
        files=files,
        task_id=task_id,
    )


def _repair_extra_args(task_id: str) -> str:
    """bd create args stamping the repair bead (labels + isolation opt-out)."""
    metadata = shlex.quote(json.dumps({"fleet_isolation": "none"}))
    return f"-l merge-fix,repairs:{task_id} --metadata {metadata}"


def _repair_live(queue: Queue, repair_task_id: str) -> bool:
    """True when the repair bead is not provably closed (lookup errors count as live)."""
    try:
        return queue.get(repair_task_id).status != TaskStatus.CLOSED.value
    except Exception:
        return True


def _apply_repair(
    queue: Queue, fleet_home: Path, task_id: str, meta: dict, note: str | None
) -> TriageApplyOutcome:
    """Spawn one repair worker for a merge-conflict block; no-op when one runs."""
    info = triage_policy.merge_conflict_info(meta)
    if info is None or not info.repo_root:
        return TriageApplyOutcome.SKIPPED
    repair_id = meta.get("repair_task_id")
    if isinstance(repair_id, str) and repair_id and _repair_live(queue, repair_id):
        return TriageApplyOutcome.SKIPPED
    coder, model = effective_coder_model(meta.get("coder"), meta.get("model"))
    description = _render_repair_description(info, task_id).strip()
    if note:
        description += f"\n\nOperator note: {note}"
    repair = queue.create_task(
        f"Resolve merge conflict: {meta.get('title') or task_id}",
        description=description,
        labels=["merge-fix", f"repairs:{task_id}"],
        cwd=info.repo_root,
        coder=coder,
        model=model,
        extra_args=_repair_extra_args(task_id),
    )
    TaskMeta.update(state_paths.task_dir(fleet_home, task_id), repair_task_id=repair.id)
    return TriageApplyOutcome.REPAIR_SPAWNED


def _live_meta(queue: Queue, meta: dict) -> dict:
    """Candidate meta with a provably-closed repair id dropped for a fresh label."""
    repair_id = meta.get("repair_task_id")
    if not isinstance(repair_id, str) or not repair_id:
        return meta
    if _repair_live(queue, repair_id):
        return meta
    return {key: value for key, value in meta.items() if key != "repair_task_id"}


def apply_answer(  # noqa: PLR0911  # ADR 0006 bead 20
    queue: Queue, fleet_home: Path, question: Question
) -> TriageApplyOutcome:
    """Apply one answered triage question; return what was done.

    The free-text ``note`` always wins over the selected option: it is
    appended to the bead description (retry/edit paths) or becomes the
    close reason. A note with no selected option is treated as edit+retry.
    Digest questions (``task_id`` None) only support "ignore all 24h".
    Returns "skipped" when the bead already moved on.
    """
    answer = question.get("answer")
    if isinstance(answer, list):
        answer = answer[0] if answer else None
    note = (question.get("note") or "").strip() or None
    task_id = question.get("task_id")

    if task_id is None:
        return _apply_digest(queue, question, answer)

    meta = _read_meta(fleet_home, task_id)
    if meta.get("status") != TaskStatus.BLOCKED.value or meta.get("blocked_at") != question.get(
        "context"
    ):
        return TriageApplyOutcome.SKIPPED

    if is_repair_answer(answer):
        return _apply_repair(queue, fleet_home, task_id, meta, note)
    if answer == CLOSE:
        reason = f"won't do: {note}" if note else "won't do (triage)"
        queue.close(task_id, reason)
        return TriageApplyOutcome.CLOSED
    if answer in (IGNORE_24H, IGNORE_FOREVER):
        queue.set_ignore(
            task_id,
            triage_policy.ignore_until_24h() if answer == IGNORE_24H else "forever",
        )
        return TriageApplyOutcome.IGNORED
    if answer == RETRY_OPUS:
        queue.set_overrides(task_id, coder="claude", model="opus")
        if note:
            _append_note_to_description(queue, fleet_home, task_id, note)
        queue.release(task_id, "triage: retry with claude/opus")
        return TriageApplyOutcome.RELEASED_OPUS
    if answer in (RETRY_SAME, EDIT_RETRY) or (answer is None and note):
        if note:
            _append_note_to_description(queue, fleet_home, task_id, note)
        queue.release(task_id, "triage: retry")
        return TriageApplyOutcome.RELEASED
    return TriageApplyOutcome.SKIPPED


def _apply_digest(queue: Queue, question: Question, answer: str | None) -> TriageApplyOutcome:
    """Apply a digest answer; only "ignore all 24h" acts, the rest is a no-op."""
    if answer != DIGEST_IGNORE_ALL:
        return TriageApplyOutcome.SKIPPED
    context = question.get("context") or ""
    ids = [i for i in context.removeprefix("digest:").split(",") if i]
    ignore_until = triage_policy.ignore_until_24h()
    for task_id in ids:
        try:
            queue.set_ignore(task_id, ignore_until)
        except Exception:
            continue
    return TriageApplyOutcome.IGNORED_ALL


def triage_tick(st: SupervisorState, store: QuestionStore) -> dict:
    """Run one triage pass: apply answered questions, then ask new ones."""
    applied = 0
    for question in store.fetch_answered_triage():
        try:
            outcome = apply_answer(st.queue, st.fleet_home, question)
        except Exception as exc:  # noqa: BLE001 - one bad apply skips, rest continue
            st.log.warning(
                "triage_apply_failed",
                question_id=question.get("id"),
                error=str(exc),
            )
            continue
        if outcome != TriageApplyOutcome.SKIPPED:
            applied += 1

    candidates = collect_candidates(st.queue, st.fleet_home, store)
    now = st.clock.now()
    waiting_ids = {c["id"] for c in candidates if waiting_for_investigation(c, st.config, now)}
    waiting = [c for c in candidates if c["id"] in waiting_ids]
    candidates = [c for c in candidates if c["id"] not in waiting_ids]
    asked = 0
    if len(candidates) > MAX_PER_TASK_QUESTIONS:
        per_task = candidates[:MAX_PER_TASK_QUESTIONS]
        rest = candidates[MAX_PER_TASK_QUESTIONS:]
        store.ask(
            triage_policy.digest_text(rest),
            list(triage_policy.DIGEST_OPTIONS),
            context="digest:" + ",".join(c["id"] for c in rest),
        )
        asked += 1
    else:
        per_task = candidates
    for cand in per_task:
        proposal = triage_policy.propose(
            cand["meta"],
            cand["attempts"],
            cand["result"],
            cand["blocked_reason"],
            investigation=cand["investigation"],
            investigation_path=cand["investigation_path"],
        )
        store.ask(
            proposal.text,
            proposal.options,
            task_id=cand["id"],
            context=cand["blocked_at"],
        )
        asked += 1
    return {
        "applied": applied,
        "asked": asked,
        "candidates": len(candidates),
        "waiting": len(waiting),
    }


class Triage:
    """Ask the operator about blocked beads on a configurable cadence."""

    order = ServiceOrder.Triage
    name = "triage"

    def __init__(self, store: QuestionStore | None = None) -> None:
        self._store = store
        self._last_tick: float | None = None

    def _question_store(self) -> QuestionStore:
        """Return the injected ask_human question store."""
        if self._store is None:
            raise FleetError("Triage service needs a question store; pass store=...")
        return self._store

    async def tick(self, st: SupervisorState) -> None:
        """Run triage_tick() when the configured interval elapsed (0 disables)."""
        interval_min = st.config.triage_interval_minutes
        if not interval_min or interval_min <= 0:
            return
        now = st.clock.monotonic()
        if self._last_tick is not None and now - self._last_tick < interval_min * 60:
            return
        self._last_tick = now
        try:
            summary = triage_tick(st, self._question_store())
        except Exception as exc:  # noqa: BLE001 - triage must not kill the loop
            st.log.warning("triage_tick_failed", error=str(exc))
        else:
            st.log.info("triage_tick", **summary)

    async def serve(self, st: SupervisorState) -> None:
        """Check the triage cadence every STATUS_LOG_INTERVAL_SEC until shutdown."""
        await run_periodic(self.name, STATUS_LOG_INTERVAL_SEC, self.tick, st)
