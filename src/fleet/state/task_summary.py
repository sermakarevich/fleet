"""Build the one task-summary dict shared by `fleet tasks` and GET /api/tasks.

Combines task.json fields with the events.jsonl scan (fleet.state.events) and
the counter files (fleet.failures), so the CLI table and the API report the
same numbers for the same task.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fleet import attempts
from fleet.coders import get_coder
from fleet.failures import failure_count, noclose_count, stall_count
from fleet.serve.beads_info import get_beads_status_map
from fleet.serve.stats import task_runtime_info_cached


def coder_context_limit(coder_name: str | None, model: str | None = None) -> int:
    if not coder_name:
        return 200_000
    try:
        return get_coder(coder_name).context_limit_for(model)
    except ValueError:
        return 200_000


def build_task_summary(task_dir: Path, data: dict, home: Path) -> dict:
    """Return the summary dict for one task.

    *data* is the task.json content, already reconciled against beads status
    (see `fleet.beads.reconcile.merge_status`) by the caller. *home* is the
    fleet home directory, needed for the blocked-reason beads fallback.
    """
    task_id = data.get("id", "")
    info = task_runtime_info_cached(task_dir)

    now = datetime.now(tz=UTC)
    started_at = info.started_at
    elapsed_sec: float | None = (now - started_at).total_seconds() if started_at else None
    idle_sec: float | None = (
        (now - info.last_event_at).total_seconds() if info.last_event_at else None
    )
    context_tokens = info.context_tokens
    context_pct: float | None = None
    if context_tokens is not None:
        limit = coder_context_limit(data.get("coder"), data.get("model"))
        context_pct = context_tokens / limit * 100

    status = data.get("status", "")
    ended_at = (
        info.last_event_at.isoformat()
        if status in ("closed", "failed") and info.last_event_at
        else None
    )

    blocked_reason = data.get("blocked_reason")
    if blocked_reason is None and status == "blocked":
        beads_status = get_beads_status_map(home) or {}
        blocked_reason = beads_status.get(task_id, {}).get("notes")

    last_attempt = attempts.last_attempt(task_dir)

    return {
        "id": task_id,
        "title": data.get("title"),
        "description": data.get("description"),
        "status": status,
        "cwd": data.get("cwd"),
        "coder": data.get("coder"),
        "model": data.get("model"),
        "priority": data.get("priority"),
        "depends_on": data.get("depends_on") or [],
        "created_at": data.get("created_at"),
        "started_at": started_at.isoformat() if started_at else None,
        "ended_at": ended_at,
        "elapsed_sec": elapsed_sec,
        "idle_sec": idle_sec,
        "events": info.events,
        "context_tokens": context_tokens,
        "context_pct": context_pct,
        "last_event_kind": info.last_event_kind,
        "last_event_detail": info.last_event_detail,
        "blocked_reason": blocked_reason,
        "blocked_at": data.get("blocked_at"),
        "failures": failure_count(task_dir),
        "noclose": noclose_count(task_dir),
        "stalls": stall_count(task_dir),
        "restarts": attempts.restart_count(task_dir),
        "last_outcome": last_attempt.get("outcome") if last_attempt else None,
        "last_outcome_reason": last_attempt.get("reason") if last_attempt else None,
        "last_action": last_attempt.get("action") if last_attempt else None,
    }
