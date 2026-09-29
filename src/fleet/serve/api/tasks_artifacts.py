"""Task artifact routes: STATE/RESULT snapshots, outputs, research, design (FR-11+)."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from fleet.serve.api.artifact_files import (
    bundle_payload,
    file_response,
    list_output_names,
    named_artifact,
    read_artifact,
)
from fleet.serve.api.models import (
    ArtifactBundle,
    ArtifactResponse,
    OutputsResponse,
)
from fleet.serve.auth import HTTP_AUTH
from fleet.serve.errors import not_found
from fleet.serve.state import StateDep
from fleet.state.artifact_locator import locate
from fleet.state.legacy_task_dir import legacy_state_text
from fleet.state.paths import task_dir as resolve_task_dir
from fleet.state.task_index import TaskIndex

router = APIRouter(prefix="/api", dependencies=[HTTP_AUTH])


@router.get("/tasks/{task_id}/artifacts/state", response_model=ArtifactResponse)
async def get_artifact_state(task_id: str, state: StateDep) -> JSONResponse:
    """STATE.md, or the legacy view for old task dirs without one."""
    task_dir = TaskIndex(state.fleet_home).find(task_id)
    if task_dir is None:
        raise not_found("task", task_id)
    f = locate(state.fleet_home, task_id, "state")
    if f.exists():
        try:
            content, mtime, resolved = await asyncio.to_thread(read_artifact, f)
        except OSError:
            raise not_found("artifact", "state") from None
        return file_response(content, mtime, resolved)
    legacy = await asyncio.to_thread(legacy_state_text, task_dir)
    if legacy is None:
        raise not_found("artifact", "state")
    return JSONResponse({"content": legacy, "mtime": 0, "path": ""})


@router.get("/tasks/{task_id}/artifacts/result", response_model=ArtifactResponse)
async def get_artifact_result(task_id: str, state: StateDep) -> JSONResponse:
    """Live RESULT.json, else the latest attempt snapshot, else legacy."""
    task_dir = TaskIndex(state.fleet_home).find(task_id)
    if task_dir is None:
        raise not_found("task", task_id)
    f = locate(state.fleet_home, task_id, "result")
    if not f.exists():
        raise not_found("artifact", "result")
    try:
        content, mtime, resolved = await asyncio.to_thread(read_artifact, f)
    except OSError:
        raise not_found("artifact", "result") from None
    return file_response(content, mtime, resolved)


@router.get("/tasks/{task_id}/artifacts/outputs", response_model=OutputsResponse)
async def get_artifact_outputs(task_id: str, state: StateDep) -> JSONResponse:
    """Deliverables under tasks/<id>/outputs/."""
    outputs = resolve_task_dir(state.fleet_home, task_id) / "outputs"
    files = await asyncio.to_thread(list_output_names, outputs)
    return JSONResponse({"files": files})


@router.get("/tasks/{task_id}/artifacts/research", response_model=ArtifactResponse)
async def get_artifact_research(task_id: str, state: StateDep) -> JSONResponse:
    """Job worker's RESEARCH.md (see workers/job.py)."""
    return await asyncio.to_thread(named_artifact, task_id, state, "RESEARCH.md")


@router.get("/tasks/{task_id}/artifacts/design", response_model=ArtifactResponse)
async def get_artifact_design(task_id: str, state: StateDep) -> JSONResponse:
    """Job worker's DESIGN.md (see workers/job.py)."""
    return await asyncio.to_thread(named_artifact, task_id, state, "DESIGN.md")


@router.get("/tasks/{task_id}/artifacts/candidates", response_model=ArtifactResponse)
async def get_artifact_candidates(task_id: str, state: StateDep) -> JSONResponse:
    """Research worker's scored shortlist, candidates.json (see workers/research.py, ADR 0015)."""
    return await asyncio.to_thread(named_artifact, task_id, state, "candidates.json")


@router.get("/tasks/{task_id}/artifacts/children_runs", response_model=ArtifactResponse)
async def get_artifact_children_runs(task_id: str, state: StateDep) -> JSONResponse:
    """Job worker's workflow-run journal, children_runs.json (see workers/job.py)."""
    return await asyncio.to_thread(named_artifact, task_id, state, "children_runs.json")


@router.get("/tasks/{task_id}/artifacts", response_model=ArtifactBundle)
async def get_artifact_bundle(task_id: str, state: StateDep) -> JSONResponse:
    """Everything the task produced, in one payload (ADR 0017 U1)."""
    task_dir = resolve_task_dir(state.fleet_home, task_id)
    if not task_dir.is_dir():
        raise not_found("task", task_id)
    raw = await asyncio.to_thread(TaskIndex(state.fleet_home).read_raw, task_id)
    return JSONResponse(await asyncio.to_thread(bundle_payload, task_dir, raw))
