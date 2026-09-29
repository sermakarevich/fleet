"""Task artifact route: the artifact bundle (ADR 0017 U1, FR-11+)."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from fleet.serve.api.artifact_files import bundle_payload
from fleet.serve.api.models import ArtifactBundle
from fleet.serve.auth import HTTP_AUTH
from fleet.serve.errors import not_found
from fleet.serve.state import StateDep
from fleet.state.paths import task_dir as resolve_task_dir
from fleet.state.task_index import TaskIndex

router = APIRouter(prefix="/api", dependencies=[HTTP_AUTH])


@router.get("/tasks/{task_id}/artifacts", response_model=ArtifactBundle)
async def get_artifact_bundle(task_id: str, state: StateDep) -> JSONResponse:
    """Everything the task produced, in one payload (ADR 0017 U1)."""
    task_dir = resolve_task_dir(state.fleet_home, task_id)
    if not task_dir.is_dir():
        raise not_found("task", task_id)
    raw = await asyncio.to_thread(TaskIndex(state.fleet_home).read_raw, task_id)
    return JSONResponse(await asyncio.to_thread(bundle_payload, task_dir, raw))
