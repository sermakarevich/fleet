"""Single-task routes: detail, children, attempts index (FR-07, FR-11)."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from fleet.beads import client as beads_client
from fleet.beads.client import BdError
from fleet.serve.api.artifact_files import children_payload
from fleet.serve.api.models import (
    TaskAttemptListResponse,
    TaskChildren,
    TaskDetail,
)
from fleet.serve.api.task_summary import build_summary, config_defaults, fetch_beads_info
from fleet.serve.auth import HTTP_AUTH
from fleet.serve.errors import not_found, unprocessable
from fleet.serve.state import StateDep
from fleet.state.task_index import TaskIndex

router = APIRouter(prefix="/api", dependencies=[HTTP_AUTH])


@router.get("/tasks/{task_id}", response_model=TaskDetail)
async def get_task(task_id: str, state: StateDep) -> JSONResponse:
    """One task summary, overlaid with beads status/priority/depends_on."""
    index = TaskIndex(state.fleet_home)
    task_dir = index.find(task_id)
    if task_dir is None:
        raise not_found("task", task_id)
    data = index.read_raw(task_id) or {}
    beads_info = await asyncio.to_thread(fetch_beads_info, task_id, state.fleet_home)
    if beads_info is not None:
        data = {**data, **beads_info}
    default_coder, default_model = config_defaults(state.config)
    summary = await asyncio.to_thread(
        build_summary,
        task_dir,
        data,
        state.fleet_home,
        default_coder=default_coder,
        default_model=default_model,
    )
    return JSONResponse(summary)


@router.get("/tasks/{task_id}/attempts", response_model=TaskAttemptListResponse)
async def list_task_attempts(task_id: str, state: StateDep) -> JSONResponse:
    """Attempt timeline for one task, derived from attempts.jsonl."""
    index = TaskIndex(state.fleet_home)
    task_dir = index.find(task_id)
    if task_dir is None:
        raise not_found("task", task_id)
    default_coder, default_model = config_defaults(state.config)
    summary = await asyncio.to_thread(
        build_summary,
        task_dir,
        index.read_raw(task_id) or {},
        state.fleet_home,
        default_coder=default_coder,
        default_model=default_model,
    )
    return JSONResponse({"attempts": summary["attempts"]})


@router.get("/tasks/{task_id}/children", response_model=TaskChildren)
async def get_task_children(task_id: str, state: StateDep) -> JSONResponse:
    """Children panel for epics: child id/status/RESULT plus CHILDREN.md."""
    index = TaskIndex(state.fleet_home)
    task_dir = index.find(task_id)
    if task_dir is None:
        raise not_found("task", task_id)
    try:
        deps = await asyncio.to_thread(beads_client.children_of, task_id, state.fleet_home)
    except BdError as exc:
        raise unprocessable(str(exc)) from exc
    payload = await asyncio.to_thread(children_payload, deps, state, task_dir)
    return JSONResponse(payload)
