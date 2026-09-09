"""Task view helpers for the serve API routers, one fleet_home.

Called by serve/api/tasks_list.py, tasks_detail.py and tasks_stream.py:
summary building (with caller-resolved context limit and blocked notes),
beads overlays, and event-row shaping. Routers stay thin: parse input,
call here, format output.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import Request

from fleet.beads import client as beads_client
from fleet.beads.status_cache import get_beads_status_map
from fleet.coders import context_limit_for
from fleet.core.config import RuntimeConfig
from fleet.core.effective import effective_coder_model
from fleet.core.task import TaskStatus
from fleet.observability.tailview import event_summary
from fleet.state.paths import task_dir as resolve_task_dir
from fleet.state.task_index import TaskIndex
from fleet.state.task_summary import (
    TaskSummary,
    build_task_summary,
    context_overrides_for_home,
)

logger = logging.getLogger(__name__)

#: Bead id prefix for this repo. `bd` auto-detects it from the directory
#: name; fleet's database issues `fleet-...` ids (confirmed via `bd list`).
#: The supervisor's claim loop applies no prefix filter (it claims every
#: ready bead), so this constant only scopes the unclaimed-bead overlay.
FLEET_BEAD_PREFIX = "fleet-"

#: `bd` metadata keys written by `fleet bd create --cwd/--coder/...` (see
#: `beads/create_args.py`). Any one of them marks a bead as fleet-owned.
FLEET_METADATA_KEYS = frozenset(
    {
        "fleet_cwd",
        "fleet_coder",
        "fleet_model",
        "fleet_worker",
        "fleet_isolation",
        "fleet_job_gate",
    }
)

#: Bead statuses surfaced as synthetic rows; terminal ones stay hidden.
VISIBLE_BEAD_STATUSES = frozenset({"open", "in_progress", "blocked", "deferred"})


def is_fleet_bead(bead: dict) -> bool:
    """True when *bead* is fleet-owned: a fleet_* metadata key or id prefix."""
    meta = bead.get("metadata") or {}
    if any(key in meta for key in FLEET_METADATA_KEYS):
        return True
    return str(bead.get("id", "")).startswith(FLEET_BEAD_PREFIX)


def _synthetic_depends_on(bead_id: str, bead: dict) -> list[str]:
    """Dependency ids declared on a `bd list` row (both envelope shapes)."""
    deps: list[str] = []
    for dep in bead.get("dependencies") or []:
        if not isinstance(dep, dict):
            continue
        target = dep.get("depends_on_id") or dep.get("id")
        if target and target != bead_id and target not in deps:
            deps.append(str(target))
    return deps


def synthetic_raw_task(bead: dict) -> dict | None:
    """Raw task.json-shaped dict for an unclaimed fleet bead, else None.

    Returns None for non-fleet beads and for terminal statuses. Reads
    cwd/coder/model from the fleet_* metadata keys that
    `fleet bd create` stores, so the UI can render the row before the
    supervisor ever claims it.
    """
    bead_id = bead.get("id")
    if not bead_id or not is_fleet_bead(bead):
        return None
    if bead.get("status") not in VISIBLE_BEAD_STATUSES:
        return None
    meta = bead.get("metadata") or {}
    return {
        "id": bead_id,
        "title": bead.get("title"),
        "description": bead.get("description"),
        "status": bead.get("status"),
        "priority": bead.get("priority"),
        "created_at": bead.get("created_at"),
        "depends_on": _synthetic_depends_on(str(bead_id), bead),
        "cwd": meta.get("fleet_cwd"),
        "coder": meta.get("fleet_coder"),
        "model": meta.get("fleet_model"),
        "has_task_dir": False,
    }


def list_unclaimed_raw_tasks(beads_map: dict[str, dict], known_ids: set[str]) -> list[dict]:
    """Synthetic raw dicts for fleet beads that have no task dir yet.

    Pure read of *beads_map* (the cached `bd list` overlay, which carries
    each bead's metadata): beads already in *known_ids* are skipped, and
    nothing is written. Returns [] when beads is unavailable.
    """
    rows: list[dict] = []
    for bead_id, info in beads_map.items():
        if bead_id in known_ids or not isinstance(info, dict):
            continue
        raw = synthetic_raw_task({"id": bead_id, **info})
        if raw is not None:
            rows.append(raw)
    return rows


def recency_key(data: Mapping[str, Any]) -> str:
    """ISO string sorting by recency descending (latest first)."""
    for key in ("ended_at", "started_at", "created_at"):
        val = data.get(key)
        if val:
            return str(val)
    return ""


def config_defaults(config: RuntimeConfig | None) -> tuple[str | None, str | None]:
    """(coder, model) defaults from the loaded runtime config, if any."""
    if config is None:
        return None, None
    return config.coder, config.model


def build_summary(
    task_dir: Path,
    data: dict,
    fleet_home: Path,
    beads_map: dict[str, dict] | None = None,
    default_coder: str | None = None,
    default_model: str | None = None,
) -> TaskSummary:
    """One task summary with caller-resolved context limit and notes."""
    overrides = context_overrides_for_home(fleet_home)
    coder, model = effective_coder_model(
        data.get("coder"), data.get("model"), default_coder, default_model
    )
    limit = context_limit_for(coder, model, overrides)
    notes: str | None = None
    if data.get("blocked_reason") is None and data.get("status") == TaskStatus.BLOCKED.value:
        resolved = beads_map if beads_map is not None else get_beads_status_map(fleet_home)
        notes = (resolved or {}).get(data.get("id", ""), {}).get("notes")
    return build_task_summary(task_dir, data, fleet_home, context_limit=limit, blocked_notes=notes)


def build_all_summaries(
    tasks: list[dict],
    fleet_home: Path,
    beads_map: dict[str, dict] | None = None,
    default_coder: str | None = None,
    default_model: str | None = None,
) -> list[TaskSummary]:
    """Summaries for raw task.json dicts (dir resolved from the id)."""
    return [
        build_summary(
            resolve_task_dir(fleet_home, d.get("id", "")),
            d,
            fleet_home,
            beads_map,
            default_coder,
            default_model,
        )
        for d in tasks
    ]


def list_raw_tasks(fleet_home: Path) -> list[dict]:
    """Raw task.json dicts for every task (runs in a thread; walks tasks/)."""
    return [raw for _, raw in TaskIndex(fleet_home).iter_meta()]


def fetch_beads_info(task_id: str, fleet_home: Path) -> dict | None:
    """{status, priority, depends_on} from bd show, or None if unavailable."""
    try:
        body = beads_client.show(task_id, fleet_home)
    except Exception as exc:
        logger.debug("bd show failed for %s: %s", task_id, exc)
        return None
    if not isinstance(body, dict):
        return None
    depends_on = [
        d["id"] for d in (body.get("dependencies") or []) if isinstance(d, dict) and d.get("id")
    ]
    return {
        "status": body.get("status"),
        "priority": body.get("priority"),
        "depends_on": depends_on,
    }


def fetch_beads_status(task_id: str, fleet_home: Path) -> str | None:
    """Beads status for one task, or None if unavailable."""
    info = fetch_beads_info(task_id, fleet_home)
    return info.get("status") if info is not None else None


def resolve_status(task_id: str, fleet_home: Path) -> str:
    """task.json status overlaid with beads status (beads wins)."""
    raw = TaskIndex(fleet_home).read_raw(task_id) or {}
    beads = fetch_beads_status(task_id, fleet_home)
    return beads if beads is not None else str(raw.get("status", ""))


def beads_assignee_clearer(fleet_home: Path) -> Callable[[str], None]:
    """clear_assignee(task_id) bound to *fleet_home*, for state.task_actions."""
    return lambda tid: beads_client.update_bead(tid, fleet_home, assignee="")


async def body_note(request: Request) -> Any:
    """Optional `note` field from a JSON body; None when absent/unparseable."""
    try:
        body = await request.json()
    except (json.JSONDecodeError, ValueError):
        return None
    return body.get("note") if isinstance(body, dict) else None


def event_to_json(row: dict, index: int = 0) -> dict:
    """Shape one state.events row for the /events endpoint contract."""
    raw_data: Any = row.get("raw", {})
    if isinstance(raw_data, str):
        try:
            raw_data = json.loads(raw_data)
        except (json.JSONDecodeError, ValueError):
            raw_data = {}
    if not isinstance(raw_data, dict):
        raw_data = {}
    row_kind = row.get("kind", "")
    return {
        "i": index,
        "ts": row.get("ts", ""),
        "kind": row_kind,
        "session_id": row.get("session_id", row.get("sessionID")),
        "tool_name": row.get("tool_name"),
        "usage": row.get("usage"),
        "summary": event_summary(row_kind, raw_data, row.get("tool_name")),
        "raw": raw_data,
    }


@dataclass
class LogEntry:
    """One parsed log.jsonl line."""

    ts: str
    level: str
    message: str
    extra: dict = field(default_factory=dict)


def parse_log_line(line: str) -> LogEntry | None:
    """Parse one log.jsonl line; None when malformed."""
    try:
        row = json.loads(line.strip())
    except (json.JSONDecodeError, ValueError):
        return None
    return LogEntry(
        ts=str(row.get("timestamp") or row.get("ts") or ""),
        level=str(row.get("level") or "info"),
        message=str(row.get("event") or row.get("message") or ""),
        extra={
            k: v
            for k, v in row.items()
            if k not in ("timestamp", "ts", "level", "event", "message")
        },
    )
