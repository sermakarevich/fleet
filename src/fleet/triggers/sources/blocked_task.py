"""One event per fleet-blocked bead (ADR 0011 first source)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

from fleet.core import triage_policy
from fleet.core.retry_policy import rounds_for_history
from fleet.state import paths as state_paths
from fleet.state.attempt_summary import render_markdown, summarize
from fleet.state.attempts import latest_attempt_dir, load_attempts
from fleet.state.task_meta import TaskMeta
from fleet.state.task_summary import read_declared_result
from fleet.triggers.model import TriggerEvent
from fleet.triggers.sources.base import SourceContext

_STDERR_TAIL_CHARS = 1500


class BlockedTaskSource:
    """One event per fleet-blocked bead; key = "<task_id>@<blocked_at>"."""

    kind: ClassVar[str] = "blocked_task"
    PARAMS: ClassVar[dict[str, str]] = {
        "fleet_blocked_only": (
            "true|false: skip beads a human blocked by hand (no blocked_reason). Default true."
        ),
        "limit": "max blocked beads read per poll. Default 100.",
    }

    def poll(self, ctx: SourceContext) -> list[TriggerEvent]:
        """Return one event per blocked bead that survives the skip rules."""
        try:
            beads = ctx.queue.list_blocked(limit=_limit(ctx.params))
        except Exception:
            return []
        fleet_only = _fleet_blocked_only(ctx.params)
        events: list[TriggerEvent] = []
        for bead in beads:
            event = _event_for(ctx, bead.id, fleet_only)
            if event is not None:
                events.append(event)
        return events


def _limit(params: dict[str, str]) -> int:
    """Poll limit from params, defaulting to 100 on missing/invalid."""
    try:
        return int(params.get("limit", "100"))
    except (TypeError, ValueError):
        return 100


def _fleet_blocked_only(params: dict[str, str]) -> bool:
    """True unless params explicitly disable the fleet-only filter."""
    raw = str(params.get("fleet_blocked_only", "true")).strip().lower()
    return raw not in ("false", "0", "no", "off")


def _event_for(ctx: SourceContext, task_id: str, fleet_only: bool) -> TriggerEvent | None:
    """Build the event for one blocked bead, or None when skipped."""
    task_dir = state_paths.task_dir(ctx.fleet_home, task_id)
    meta = TaskMeta.load(task_dir)
    data = meta.to_dict() if meta is not None else {}
    blocked_reason = str(data.get("blocked_reason") or "")
    if fleet_only and not blocked_reason:
        return None
    if triage_policy.ignore_active(_opt_str(data.get("ignore_until")), ctx.now):
        return None
    if "fleet_trigger_id" in data:
        return None
    blocked_at = str(data.get("blocked_at") or "")
    key = f"{task_id}@{blocked_at or 'unknown'}"
    occurred = blocked_at or ctx.now.isoformat()
    payload = _payload(task_id, task_dir, data, blocked_reason, blocked_at)
    return TriggerEvent(
        source=BlockedTaskSource.kind, key=key, occurred_at=occurred, payload=payload
    )


def _opt_str(value: Any) -> str | None:
    """Pass through strings, map anything else to None."""
    return value if isinstance(value, str) else None


def _payload(
    task_id: str, task_dir: Path, data: dict[str, Any], blocked_reason: str, blocked_at: str
) -> dict[str, str]:
    """Flat string payload for one blocked-bead event."""
    history = load_attempts(task_dir)
    declared = read_declared_result(task_dir)
    status = declared.get("status") if isinstance(declared, dict) else None
    return {
        "task_id": task_id,
        "title": str(data.get("title") or ""),
        "blocked_reason": blocked_reason,
        "blocked_at": blocked_at,
        "cwd": str(data.get("cwd") or ""),
        "task_dir": str(task_dir.absolute()),
        "coder": str(data.get("coder") or ""),
        "model": str(data.get("model") or ""),
        "rounds": str(rounds_for_history(history)),
        "result_status": str(status or ""),
        "stderr_tail": _stderr_tail(task_dir),
    }


def _stderr_tail(task_dir: Path) -> str:
    """Last 1500 chars of the latest attempt's summary, or ""."""
    attempt_dir = latest_attempt_dir(task_dir)
    if attempt_dir is None:
        return ""
    try:
        n = int(attempt_dir.name)
    except ValueError:
        return ""
    try:
        text = render_markdown(summarize(task_dir, n))
    except (OSError, ValueError):
        return ""
    return text.strip()[-_STDERR_TAIL_CHARS:] or ""
