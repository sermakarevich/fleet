"""Build the one task-summary dict shared by `fleet tasks` and GET /api/tasks.

Combines task.json fields with the events.jsonl scan (fleet.state.events) and
the counter files (fleet.state.counters), so the CLI table and the API report the
same numbers for the same task.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from fleet.beads.cache import get_beads_status_map
from fleet.coders import get_coder
from fleet.core.result import parse_result
from fleet.serve.stats import task_runtime_info_cached
from fleet.state import attempts
from fleet.state.counters import failure_count, noclose_count, stall_count

_HANDOFF_EXCERPT_MAX = 2048


def coder_context_limit(coder_name: str | None, model: str | None = None) -> int:
    if not coder_name:
        return 200_000
    try:
        return get_coder(coder_name).context_limit_for(model)
    except ValueError:
        return 200_000


def _read_result(task_dir: Path) -> dict | None:
    """Read and parse artifacts/RESULT.json, if present."""
    result_file = task_dir / "artifacts" / "RESULT.json"
    try:
        text = result_file.read_text(encoding="utf-8")
    except OSError:
        return None
    result = parse_result(text)
    return asdict(result) if result is not None else None


def _read_run_info(task_dir: Path) -> tuple[str | None, list]:
    """Read the worker name and step timeline from the latest attempt's run.json."""
    run_file = task_dir / "run.json"
    try:
        data = json.loads(run_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, []
    if not isinstance(data, dict):
        return None, []
    steps = data.get("steps")
    return data.get("worker"), steps if isinstance(steps, list) else []


def _read_handoff_excerpt(task_dir: Path) -> str | None:
    """Read artifacts/HANDOFF.md, truncated to the hard cap fleet enforces."""
    handoff_file = task_dir / "artifacts" / "HANDOFF.md"
    try:
        text = handoff_file.read_text(encoding="utf-8")
    except OSError:
        return None
    return text[:_HANDOFF_EXCERPT_MAX]


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
    worker, steps = _read_run_info(task_dir)

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
        "result": _read_result(task_dir),
        "handoff_excerpt": _read_handoff_excerpt(task_dir),
        "worker": worker,
        "steps": steps,
    }
