"""Supervisor triage loop over blocked beads.

Blocked tasks pile up silently; this scheduled loop (part of the status
loop, every ``cfg.triage_interval_minutes``; 0 disables) posts one
non-blocking ask_human question per blocked bead with a rule-based fix
proposal (see core/triage_policy.py) and applies the operator's answer on
the next tick.

Applied answers change bead state (release/close/ignore), so an
already-applied question no longer matches its bead's live blocked state
and is skipped naturally — no consumed-markers needed.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from fleet.core import triage_policy
from fleet.core.result import parse_result
from fleet.core.retry_policy import rounds_for_history
from fleet.core.triage_policy import (
    CLOSE,
    DIGEST_IGNORE_ALL,
    EDIT_RETRY,
    IGNORE_24H,
    IGNORE_FOREVER,
    MAX_PER_TASK_QUESTIONS,
    RETRY_OPUS,
    RETRY_SAME,
)
from fleet.state import attempts as attempts_mod
from fleet.state.attempt_summary import render_markdown, summarize
from fleet.state.attempts import latest_attempt_dir
from fleet.state.legacy import legacy_result
from fleet.state.paths import RESULT_JSON
from fleet.state.paths import task_dir as _task_dir

# How many of the newest attempts count for "rate-limit history".
_RATE_LIMIT_WINDOW = 5
# Characters of the derived attempt-summary tail shown for exhausted failure rounds.
_STDERR_TAIL_CHARS = 1500


def _read_meta(project_root: Path, task_id: str) -> dict:
    """Read task.json; {} when missing or unparsable."""
    try:
        data = json.loads((_task_dir(project_root, task_id) / "task.json").read_text())
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


def _read_result(task_dir: Path) -> dict | None:
    """Parsed task-level RESULT.json as a plain dict, or None.

    Falls back to the latest attempt's RESULT.json snapshot, then to the
    legacy artifacts/RESULT.json for old task dirs.
    """
    for path in (
        task_dir / RESULT_JSON,
        *(
            [latest_attempt_dir(task_dir) / RESULT_JSON]
            if latest_attempt_dir(task_dir) is not None
            else []
        ),
    ):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        result = parse_result(text)
        if result is not None:
            return asdict(result)
    legacy = legacy_result(task_dir)
    if legacy is None:
        return None
    try:
        result = parse_result(json.dumps(legacy))
    except (ValueError, TypeError):
        return None
    return asdict(result) if result is not None else None


def collect_candidates(
    queue: Any, project_root: Path, store: Any, limit: int = 100
) -> list[dict]:
    """Blocked beads that need a triage question.

    Skipped: beads without task.json ``blocked_reason`` (human-blocked, not
    fleet-blocked), tasks with an active ``ignore_until``, and tasks with a
    triage question already pending for their current ``blocked_at``.
    """
    candidates: list[dict] = []
    try:
        blocked = queue.list_blocked(limit=limit)
    except Exception:
        return []
    for bead in blocked:
        task_id = bead.id if hasattr(bead, "id") else bead.get("id")
        meta = _read_meta(project_root, task_id)
        blocked_reason = meta.get("blocked_reason")
        if not blocked_reason:
            continue
        if triage_policy.ignore_active(meta.get("ignore_until")):
            continue
        blocked_at = meta.get("blocked_at")
        if store.fetch_pending_for_task(task_id, blocked_at):
            continue
        task_dir = _task_dir(project_root, task_id)
        history = attempts_mod.load_attempts(task_dir)
        rounds = rounds_for_history(history)
        rate_limited = any(
            h.get("outcome") == "rate_limit" for h in history[-_RATE_LIMIT_WINDOW:]
        )
        candidates.append(
            {
                "id": task_id,
                "title": meta.get("title", getattr(bead, "title", "")),
                "description": meta.get("description"),
                "blocked_reason": blocked_reason,
                "blocked_at": blocked_at,
                "attempts": {
                    "rounds": rounds,
                    "rate_limited": rate_limited,
                    "stderr_tail": _stderr_tail(task_dir),
                },
                "result": _read_result(task_dir),
            }
        )
    return candidates


def _append_note_to_description(queue: Any, project_root: Path, task_id: str, note: str) -> None:
    """Append the operator's note as a paragraph to the bead description."""
    current = _read_meta(project_root, task_id).get("description") or ""
    updated = f"{current}\n\nOperator note: {note}" if current else f"Operator note: {note}"
    queue.set_bd_fields(task_id, {"description": updated})


def apply_answer(queue: Any, project_root: Path, question: dict) -> str:
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

    meta = _read_meta(project_root, task_id)
    if meta.get("status") != "blocked" or meta.get("blocked_at") != question.get("context"):
        return "skipped"

    if answer == CLOSE:
        reason = f"won't do: {note}" if note else "won't do (triage)"
        queue.close(task_id, reason)
        return "closed"
    if answer in (IGNORE_24H, IGNORE_FOREVER):
        queue.set_ignore(
            task_id,
            triage_policy.ignore_until_24h() if answer == IGNORE_24H else "forever",
        )
        return "ignored"
    if answer == RETRY_OPUS:
        queue.set_overrides(task_id, coder="claude", model="opus")
        if note:
            _append_note_to_description(queue, project_root, task_id, note)
        queue.release(task_id, "triage: retry with claude/opus")
        return "released-opus"
    if answer in (RETRY_SAME, EDIT_RETRY) or (answer is None and note):
        if note:
            _append_note_to_description(queue, project_root, task_id, note)
        queue.release(task_id, "triage: retry")
        return "released"
    return "skipped"


def _apply_digest(queue: Any, question: dict, answer: str | None) -> str:
    """Apply a digest answer; only "ignore all 24h" acts, the rest is a no-op."""
    if answer != DIGEST_IGNORE_ALL:
        return "skipped"
    context = question.get("context") or ""
    ids = [i for i in context.removeprefix("digest:").split(",") if i]
    ignore_until = triage_policy.ignore_until_24h()
    for task_id in ids:
        try:
            queue.set_ignore(task_id, ignore_until)
        except Exception:
            continue
    return "ignored-all"


class TriageMixin:
    """Scheduled triage tick; mixed into Supervisor (orchestrator/supervisor.py)."""

    _triage_store: Any = None
    _last_triage_tick: float | None = None

    def _triage_question_store(self) -> Any:
        from fleet.integrations.ask_human.store import QuestionStore

        if self._triage_store is None:
            self._triage_store = QuestionStore()
        return self._triage_store

    def triage_tick_if_due(self) -> None:
        """Run triage_tick() when the configured interval elapsed (0 disables)."""
        interval_min = getattr(self.config, "triage_interval_minutes", 15)
        if not interval_min or interval_min <= 0:
            return
        # Queues without list_blocked (old test doubles) don't support triage.
        if not hasattr(self._queue, "list_blocked"):
            return
        now = time.monotonic()
        last = self._last_triage_tick
        if last is not None and now - last < interval_min * 60:
            return
        self._last_triage_tick = now
        try:
            summary = self.triage_tick()
        except Exception as exc:  # noqa: BLE001 - triage must not kill the loop
            self._log.warning("triage_tick_failed", error=str(exc))
        else:
            self._log.info("triage_tick", **summary)

    def triage_tick(self) -> dict:
        """One triage pass: apply answered questions, then ask new ones."""
        store = self._triage_question_store()
        applied = 0
        for question in store.fetch_answered_triage():
            try:
                outcome = apply_answer(self._queue, self._project_root, question)
            except Exception as exc:  # noqa: BLE001 - one bad apply skips, rest continue
                self._log.warning(
                    "triage_apply_failed",
                    question_id=question.get("id"),
                    error=str(exc),
                )
                continue
            if outcome != "skipped":
                applied += 1

        candidates = collect_candidates(self._queue, self._project_root, store)
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
                {"id": cand["id"], "title": cand["title"]},
                cand["attempts"],
                cand["result"],
                cand["blocked_reason"],
            )
            store.ask(
                proposal.text,
                proposal.options,
                task_id=cand["id"],
                context=cand["blocked_at"],
            )
            asked += 1
        return {"applied": applied, "asked": asked, "candidates": len(candidates)}
