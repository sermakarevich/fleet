"""Task collection routes: list, create, coders, templates (FR-07)."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from fleet.beads.client import BdError
from fleet.beads.reconcile import merge_status
from fleet.beads.status_cache import get_beads_status_map
from fleet.coders import get_coder, list_coders
from fleet.core.limits import CLOSED_TASKS_DEFAULT, CLOSED_TASKS_MAX
from fleet.serve.api.artifact_files import read_templates
from fleet.serve.api.models import (
    CoderListResponse,
    CreateTaskResponse,
    TaskListResponse,
    TemplateListResponse,
)
from fleet.serve.api.task_summary import (
    build_all_summaries,
    config_defaults,
    list_raw_tasks,
    recency_key,
)
from fleet.serve.auth import HTTP_AUTH
from fleet.serve.errors import parse_json_body, unprocessable
from fleet.serve.state import StateDep

router = APIRouter(prefix="/api", dependencies=[HTTP_AUTH])


@router.get("/tasks", response_model=TaskListResponse)
async def list_tasks(
    state: StateDep,
    closed_limit: int = Query(default=CLOSED_TASKS_DEFAULT, ge=0, le=CLOSED_TASKS_MAX),
) -> JSONResponse:
    """List task summaries, active first then recently-closed (FR-07)."""
    fleet_home = state.fleet_home
    raw_tasks = await asyncio.to_thread(list_raw_tasks, fleet_home)
    beads_map = await asyncio.to_thread(get_beads_status_map, fleet_home)
    reconciled = [
        merge_status(raw, beads_map.get(raw.get("id", "")))
        if beads_map is not None and raw.get("id", "")
        else raw
        for raw in raw_tasks
    ]
    active = [d for d in reconciled if d.get("status") not in ("closed", "failed")]
    closed = [d for d in reconciled if d.get("status") in ("closed", "failed")]
    closed.sort(key=recency_key, reverse=True)
    if closed_limit > 0:
        closed = closed[:closed_limit]
    default_coder, default_model = config_defaults(state.config)
    summaries = await asyncio.to_thread(
        build_all_summaries,
        active + closed,
        fleet_home,
        beads_map,
        default_coder=default_coder,
        default_model=default_model,
    )
    summaries.sort(key=lambda s: recency_key(s) or "", reverse=True)
    return JSONResponse({"tasks": summaries})


@router.get("/coders", response_model=CoderListResponse)
async def coders() -> JSONResponse:
    """Coders the create-task form may offer."""
    return JSONResponse({"coders": list_coders()})


@router.post("/tasks", response_model=CreateTaskResponse)
async def create_task(request: Request, state: StateDep) -> JSONResponse:
    """Create a task via the queue; 201 with the new id."""
    body = await parse_json_body(request)
    if not isinstance(body, dict):
        raise unprocessable("task body must be a JSON object")
    title: str = (body.get("title") or "").strip()
    if not title:
        raise unprocessable("title is required")
    coder = body.get("coder")
    if coder:
        try:
            get_coder(coder)
        except ValueError as exc:
            raise unprocessable(str(exc)) from exc
    try:
        task = await asyncio.to_thread(
            state.queue.create_task,
            title,
            body.get("description"),
            body.get("dependencies"),
            None,
            body.get("cwd"),
            coder,
            body.get("model"),
            body.get("args"),
        )
    except BdError as exc:
        raise unprocessable(str(exc)) from exc
    return JSONResponse({"id": task.id}, status_code=201)


@router.get("/templates", response_model=TemplateListResponse)
async def list_templates(state: StateDep) -> JSONResponse:
    """Prompt templates stored under the fleet home."""
    templates = await asyncio.to_thread(read_templates, state.fleet_home / "templates")
    return JSONResponse({"templates": templates})
