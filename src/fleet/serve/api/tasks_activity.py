"""Task activity feed: one merged events+log stream per task (ADR 0017 U1)."""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from fleet.core.limits import MAX_EVENT_PAGE
from fleet.serve.api.activity_reads import activity_payload
from fleet.serve.api.models import ActivityResponse
from fleet.serve.auth import HTTP_AUTH
from fleet.serve.errors import not_found, unprocessable
from fleet.serve.state import StateDep
from fleet.state.paths import task_dir as resolve_task_dir

router = APIRouter(prefix="/api", dependencies=[HTTP_AUTH])

_LEVELS = ("debug", "info", "warning", "error")


@router.get("/tasks/{task_id}/activity", response_model=ActivityResponse)
async def get_task_activity(
    task_id: str,
    state: StateDep,
    after: int | None = Query(default=None, ge=0),
    before: int | None = Query(default=None, ge=0),
    limit: int = Query(default=200, ge=1, le=MAX_EVENT_PAGE),
    min_level: str = Query(default="warning"),
) -> JSONResponse:
    """Merged coder-events + fleet-log feed across attempts, cursor-paged."""
    if after is not None and before is not None:
        raise unprocessable("after and before are mutually exclusive")
    level = min_level.lower()
    if level not in _LEVELS:
        raise unprocessable(f"unknown min_level: {min_level}")
    task_dir: Path = resolve_task_dir(state.fleet_home, task_id)
    if not task_dir.is_dir():
        raise not_found("task", task_id)
    payload = await asyncio.to_thread(activity_payload, task_dir, level)
    feed: list[dict] = payload["items"]
    if after is not None:
        page = [row for row in feed if row["seq"] > after][:limit]
    elif before is not None:
        page = [row for row in feed if row["seq"] < before][-limit:]
    else:
        page = feed[-limit:]
    return JSONResponse(
        {
            "items": page,
            "total": payload["total"],
            "has_earlier": bool(page) and page[0]["seq"] > 0,
            "latest_attempt": payload["latest_attempt"],
            "stderr": payload["stderr"],
        }
    )
