"""Task artifact routes: STATE/RESULT snapshots, outputs, research, design (FR-11+)."""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from fleet.serve.state import AppState, StateDep
from fleet.state.artifact_locator import locate
from fleet.state.legacy import legacy_state_text
from fleet.state.paths import task_dir as resolve_task_dir
from fleet.state.task_index import TaskIndex

router = APIRouter(prefix="/api")


def _file_response(f: Path) -> JSONResponse:
    return JSONResponse(
        {
            "content": f.read_text(encoding="utf-8"),
            "mtime": f.stat().st_mtime,
            "path": str(f.resolve()),
        }
    )


@router.get("/tasks/{task_id}/artifacts/state")
async def get_artifact_state(task_id: str, state: StateDep) -> JSONResponse:
    """STATE.md, or the legacy view for old task dirs without one."""
    task_dir = TaskIndex(state.home).find(task_id)
    if task_dir is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    f = locate(state.home, task_id, "state")
    if f.exists():
        return _file_response(f)
    legacy = legacy_state_text(task_dir)
    if legacy is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse({"content": legacy, "mtime": 0, "path": ""})


@router.get("/tasks/{task_id}/artifacts/result")
async def get_artifact_result(task_id: str, state: StateDep) -> JSONResponse:
    """Live RESULT.json, else the latest attempt snapshot, else legacy."""
    task_dir = TaskIndex(state.home).find(task_id)
    if task_dir is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    f = locate(state.home, task_id, "result")
    if not f.exists():
        return JSONResponse({"error": "not found"}, status_code=404)
    return _file_response(f)


@router.get("/tasks/{task_id}/artifacts/outputs")
async def get_artifact_outputs(task_id: str, state: StateDep) -> JSONResponse:
    """Deliverables under tasks/<id>/outputs/."""
    outputs = resolve_task_dir(state.home, task_id) / "outputs"
    if not outputs.is_dir():
        return JSONResponse({"files": []})
    try:
        files = sorted(p.name for p in outputs.iterdir() if p.is_file())
    except OSError:
        files = []
    return JSONResponse({"files": files})


@router.get("/tasks/{task_id}/artifacts/research")
async def get_artifact_research(task_id: str, state: StateDep) -> JSONResponse:
    """Job worker's RESEARCH.md (see workers/job.py)."""
    return _named_artifact(task_id, state, "RESEARCH.md")


@router.get("/tasks/{task_id}/artifacts/design")
async def get_artifact_design(task_id: str, state: StateDep) -> JSONResponse:
    """Job worker's DESIGN.md (see workers/job.py)."""
    return _named_artifact(task_id, state, "DESIGN.md")


def _named_artifact(task_id: str, state: AppState, filename: str) -> JSONResponse:
    f = resolve_task_dir(state.home, task_id) / "artifacts" / filename
    if not f.exists():
        return JSONResponse({"error": "not found"}, status_code=404)
    return _file_response(f)


@router.get("/tasks/{task_id}/diff")
async def get_task_diff(task_id: str, state: StateDep) -> JSONResponse:
    """git diff of the task's cwd (empty when not a git repo)."""
    raw = TaskIndex(state.home).read_raw(task_id) or {}
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
