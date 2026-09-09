"""Build the one task-summary dict shared by `fleet tasks` and GET /api/tasks.

Combines task.json fields with the events.jsonl scan (fleet.state.events) and
the attempt-history rounds (fleet.core.retry_policy), so the CLI table and the
API report the same numbers for the same task. Callers reconcile queue status
beforehand (see `fleet.beads.reconcile.merge_status`) and pass the resolved
context window and blocked-notes fallback in — this module imports core and
state only.
"""

from __future__ import annotations

import json
import tomllib
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict

from fleet.core.context_window import parse_context_windows
from fleet.core.process import pid_alive
from fleet.core.result import parse_result
from fleet.core.retry_policy import rounds_for_history
from fleet.core.task import AttemptKind, TaskOutcome, TaskStatus
from fleet.core.triage_policy import ignore_active
from fleet.state import attempts
from fleet.state.artifacts import ResultFile, StateFile
from fleet.state.attempts import latest_attempt_dir
from fleet.state.events import iter_attempt_events, scan_rows
from fleet.state.legacy import legacy_result, legacy_state_text
from fleet.state.paths import attempt_dir
from fleet.state.run_file import RunRecord
from fleet.state.runtime_stats import task_runtime_info_cached

_STATE_EXCERPT_MAX = 6144

#: Context window used when the caller passes no resolved limit.
DEFAULT_CONTEXT_LIMIT = 200_000


class LeaseInfo(TypedDict):
    """Claim lease from the latest attempt's run.json, with pid liveness."""

    heartbeat_at: str
    lease_until: str
    alive: bool


class AttemptTimelineRow(TypedDict):
    """One per-attempt row of the attempts timeline (newest last)."""

    n: int
    kind: str
    mode: str | None
    coder: str | None
    model: str | None
    started_at: str | None
    ended_at: str | None
    duration_sec: float | None
    outcome: str | None
    reason: str | None
    peak_context_pct: float | None
    context_badge: bool
    files_touched: int
    commits: list[str]
    result: dict | None
    has_summary: bool
    has_prompt: bool


class TaskSummary(TypedDict):
    """The one task-summary shape shared by `fleet tasks` and GET /api/tasks."""

    id: str
    title: str | None
    description: str | None
    status: str
    cwd: str | None
    coder: str | None
    model: str | None
    priority: int | None
    depends_on: list[str]
    created_at: str | None
    started_at: str | None
    ended_at: str | None
    elapsed_sec: float | None
    idle_sec: float | None
    events: int
    context_tokens: int | None
    context_pct: float | None
    context_limit: int
    last_event_kind: str | None
    last_event_detail: str | None
    blocked_reason: str | None
    blocked_at: str | None
    ignore_until: str | None
    ignored: bool
    rounds: dict[str, int]
    context_rounds: int
    compactions: int
    peak_context_pct: float | None
    restarts: int
    last_outcome: str | None
    last_outcome_reason: str | None
    last_action: str | None
    result: dict | None
    state_excerpt: str | None
    worker: str | None
    job_phase: str | None
    job_artifacts: dict[str, bool]
    steps: list
    lease: LeaseInfo | None
    attempts: list[AttemptTimelineRow]


def context_overrides_for_home(fleet_home: Path) -> dict[str, int]:
    """Parse ``context_windows`` from ``<fleet_home>/runtime.toml`` into ``{model: tokens}``.

    Missing file, missing key, or malformed value all yield {} (built-in
    table only) — the summary display must never crash on config drift.
    Never creates the file: plain ``tomllib`` read, no ``core.config.load``.
    """

    try:
        with (fleet_home / "runtime.toml").open("rb") as fh:
            raw = tomllib.load(fh).get("context_windows", "")
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, str):
        return {}
    try:
        return parse_context_windows(raw)
    except ValueError:
        return {}


def _parse_result_text(text: str) -> dict | None:
    result = parse_result(text)
    return asdict(result) if result is not None else None


def read_declared_result(task_dir: Path) -> dict | None:
    """The task's latest declared result as a plain dict, or None.

    Reads the live task-level RESULT.json first (present between worker
    exit and reap), then the latest attempt's RESULT.json snapshot, then
    the legacy artifacts/RESULT.json for old task dirs.
    """
    try:
        return _parse_result_text(ResultFile.path(task_dir).read_text(encoding="utf-8"))
    except OSError:
        pass
    attempt_dir = latest_attempt_dir(task_dir)
    if attempt_dir is not None:
        try:
            parsed = _parse_result_text(
                ResultFile.snapshot_path(attempt_dir).read_text(encoding="utf-8")
            )
        except OSError:
            parsed = None
        if parsed is not None:
            return parsed
    legacy = legacy_result(task_dir)
    if legacy is None:
        return None
    try:
        result = parse_result(json.dumps(legacy))
    except (ValueError, TypeError):
        return None
    return asdict(result) if result is not None else None


def _read_run_info(task_dir: Path) -> tuple[str | None, list]:
    """Read the worker name and step timeline from the latest attempt's run.json."""
    attempt_dir = latest_attempt_dir(task_dir)
    if attempt_dir is None:
        return None, []
    run = RunRecord.load(attempt_dir)
    if run is None:
        return None, []
    return run.worker, run.steps


def _read_lease(task_dir: Path) -> LeaseInfo | None:
    """Read the claim lease from the latest attempt's run.json, if any.

    Returns ``{"heartbeat_at", "lease_until", "alive"}`` where *alive*
    probes the recorded pid. Returns None when there is no attempt, no
    run.json, or no heartbeat keys (old attempts, human-claimed beads).
    """
    attempt_dir = latest_attempt_dir(task_dir)
    if attempt_dir is None:
        return None
    run = RunRecord.load(attempt_dir)
    if run is None:
        return None
    heartbeat_at = run.heartbeat_at
    lease_until = run.lease_until
    if not isinstance(heartbeat_at, str) or not isinstance(lease_until, str):
        return None
    return {
        "heartbeat_at": heartbeat_at,
        "lease_until": lease_until,
        "alive": pid_alive(run.pid),
    }


def _read_json_file(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _build_attempts_summary(task_dir: Path, limit: int) -> list[AttemptTimelineRow]:
    """Per-attempt summary rows for the attempts timeline (newest last)."""
    rows: list[AttemptTimelineRow] = []
    for entry in attempts.load_attempts(task_dir):
        n = entry["n"]
        adir = attempt_dir(task_dir, n)
        run = RunRecord.load(adir)
        raw_launch = run.launch if run is not None else None
        launch: dict = raw_launch if isinstance(raw_launch, dict) else {}
        result = _read_json_file(adir / "RESULT.json")
        stats = scan_rows(iter_attempt_events(task_dir, n))
        peak_context_pct = (
            stats.peak_context_tokens / limit * 100
            if stats.peak_context_tokens is not None
            else None
        )
        outcome = entry.get("outcome")
        rows.append(
            {
                "n": n,
                "kind": launch.get("kind", entry.get("kind", AttemptKind.WORK.value)),
                "mode": launch.get("mode"),
                "coder": entry.get("coder"),
                "model": entry.get("model"),
                "started_at": entry.get("started_at"),
                "ended_at": entry.get("ended_at"),
                "duration_sec": entry.get("duration_sec"),
                "outcome": outcome,
                "reason": entry.get("reason"),
                "peak_context_pct": peak_context_pct,
                # "context" badge for the Attempts timeline on
                # CONTEXT_PRESSURE attempts; "compaction" label comes
                # from kind == "compact" with its own row style.
                "context_badge": outcome == TaskOutcome.CONTEXT_PRESSURE.value,
                "files_touched": stats.files_touched_count,
                "commits": (result or {}).get("commits") or [],
                "result": result,
                # The summary is derived on demand (never stored), so it
                # always exists; the prompt is recorded per attempt.
                "has_summary": True,
                "has_prompt": (adir / "prompt.md").exists(),
            }
        )
    return rows


def _read_state_excerpt(task_dir: Path) -> str | None:
    """Read STATE.md, truncated to the worker-memory cap fleet enforces."""
    state_path = StateFile.path(task_dir)
    if state_path.exists():
        try:
            return state_path.read_text(encoding="utf-8")[:_STATE_EXCERPT_MAX]
        except OSError:
            pass
    legacy = legacy_state_text(task_dir)
    if legacy is None:
        return None
    return legacy[:_STATE_EXCERPT_MAX]


def _job_phase(worker: str | None) -> str | None:
    """The job phase badge, from the latest attempt's worker name.

    ``job.research`` -> ``research``; non-job workers (and no attempt yet)
    yield None. Mirrors ``core/job_phase.phase`` without re-reading files:
    the worker name already records which phase last ran.
    """
    if worker and worker.startswith("job."):
        return worker.removeprefix("job.")
    return None


def _job_artifacts(task_dir: Path) -> dict:
    """Presence flags for the job worker's RESEARCH.md/DESIGN.md/tasks.json/APPROVED."""
    artifacts = task_dir / "artifacts"
    return {
        "research": (artifacts / "RESEARCH.md").exists(),
        "design": (artifacts / "DESIGN.md").exists(),
        "tasks": (artifacts / "tasks.json").exists(),
        "approved": (artifacts / "APPROVED").exists(),
    }


def build_task_summary(
    task_dir: Path,
    data: dict,
    fleet_home: Path,
    *,
    context_limit: int | None = None,
    blocked_notes: str | None = None,
) -> TaskSummary:
    """Return the summary dict for one task.

    *data* is the task.json content, already reconciled against beads status
    (see `fleet.beads.reconcile.merge_status`) by the caller. *fleet_home* is the
    fleet fleet_home directory. *context_limit* is the resolved coder/model window
    (defaults to DEFAULT_CONTEXT_LIMIT); *blocked_notes* is the beads-notes
    fallback used when a blocked task has no blocked_reason.
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
    limit = context_limit if context_limit is not None else DEFAULT_CONTEXT_LIMIT
    if context_tokens is not None:
        context_pct = context_tokens / limit * 100

    status = data.get("status", "")
    ended_at = (
        info.last_event_at.isoformat()
        if status in ("closed", "failed") and info.last_event_at
        else None
    )

    blocked_reason = data.get("blocked_reason")
    if blocked_reason is None and status == TaskStatus.BLOCKED.value:
        blocked_reason = blocked_notes

    ignore_until = data.get("ignore_until")

    last_attempt = attempts.last_attempt(task_dir)
    worker, steps = _read_run_info(task_dir)
    history = attempts.load_attempts(task_dir)
    rounds = rounds_for_history(history)
    attempt_rows = _build_attempts_summary(task_dir, limit)
    compactions = sum(1 for h in history if h.get("kind") == AttemptKind.COMPACT.value)
    latest_peak_context_pct = attempt_rows[-1]["peak_context_pct"] if attempt_rows else None

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
        "context_limit": limit,
        "last_event_kind": info.last_event_kind,
        "last_event_detail": info.last_event_detail,
        "blocked_reason": blocked_reason,
        "blocked_at": data.get("blocked_at"),
        "ignore_until": ignore_until,
        "ignored": ignore_active(ignore_until),
        "rounds": rounds,
        "context_rounds": rounds.get("context", 0),
        "compactions": compactions,
        "peak_context_pct": latest_peak_context_pct,
        "restarts": attempts.restart_count(task_dir),
        "last_outcome": last_attempt.get("outcome") if last_attempt else None,
        "last_outcome_reason": last_attempt.get("reason") if last_attempt else None,
        "last_action": last_attempt.get("action") if last_attempt else None,
        "result": read_declared_result(task_dir),
        "state_excerpt": _read_state_excerpt(task_dir),
        "worker": worker,
        "job_phase": _job_phase(worker),
        "job_artifacts": _job_artifacts(task_dir),
        "steps": steps,
        "lease": _read_lease(task_dir),
        "attempts": attempt_rows,
    }
