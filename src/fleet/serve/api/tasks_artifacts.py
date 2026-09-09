"""Task artifact routes: STATE/RESULT snapshots, outputs, research, design (FR-11+)."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from fleet.serve.api.artifact_files import (
    file_response,
    list_output_names,
    named_artifact,
    read_artifact,
)
from fleet.serve.api.models import (
    ArtifactResponse,
    DiffResponse,
    OutputsResponse,
)
from fleet.serve.state import StateDep
from fleet.state.artifact_locator import locate
from fleet.state.legacy_task_dir import legacy_state_text
from fleet.state.paths import task_dir as resolve_task_dir
from fleet.state.task_index import TaskIndex

router = APIRouter(prefix="/api")


@router.get("/tasks/{task_id}/artifacts/state", response_model=ArtifactResponse)
async def get_artifact_state(task_id: str, state: StateDep) -> JSONResponse:
    """STATE.md, or the legacy view for old task dirs without one."""
    task_dir = TaskIndex(state.fleet_home).find(task_id)
    if task_dir is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    f = locate(state.fleet_home, task_id, "state")
    if f.exists():
        try:
            content, mtime, resolved = await asyncio.to_thread(read_artifact, f)
        except OSError:
            return JSONResponse({"error": "not found"}, status_code=404)
        return file_response(content, mtime, resolved)
    legacy = await asyncio.to_thread(legacy_state_text, task_dir)
    if legacy is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse({"content": legacy, "mtime": 0, "path": ""})


@router.get("/tasks/{task_id}/artifacts/result", response_model=ArtifactResponse)
async def get_artifact_result(task_id: str, state: StateDep) -> JSONResponse:
    """Live RESULT.json, else the latest attempt snapshot, else legacy."""
    task_dir = TaskIndex(state.fleet_home).find(task_id)
    if task_dir is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    f = locate(state.fleet_home, task_id, "result")
    if not f.exists():
        return JSONResponse({"error": "not found"}, status_code=404)
    try:
        content, mtime, resolved = await asyncio.to_thread(read_artifact, f)
    except OSError:
        return JSONResponse({"error": "not found"}, status_code=404)
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


@router.get("/tasks/{task_id}/diff", response_model=DiffResponse)
async def get_task_diff(task_id: str, state: StateDep) -> JSONResponse:
    """git diff of the task's cwd (empty when not a git repo)."""
    raw = TaskIndex(state.fleet_home).read_raw(task_id) or {}
    cwd = raw.get("cwd")
    if not cwd:
        return JSONResponse({"diff": ""})
    try:
        proc = await asyncio.create_subprocess_exec(
            "git",
            "-C",
            cwd,
            "diff",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
        diff_text = stdout.decode("utf-8", errors="replace") if stdout else ""
    except (TimeoutError, OSError):
        diff_text = ""
    return JSONResponse({"diff": diff_text})
