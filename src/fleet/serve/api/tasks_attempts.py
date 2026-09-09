"""Per-attempt routes: derived summary, prompt, state snapshot, log."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from fleet.serve.api.models import ContentResponse
from fleet.serve.state import AppState, StateDep
from fleet.state.attempt_summary import render_markdown, summarize
from fleet.state.legacy import attempt_state_snapshot
from fleet.state.paths import attempt_dir_path
from fleet.state.task_index import TaskIndex

router = APIRouter(prefix="/api")


def _attempt_dir(task_id: str, n: int, state: AppState) -> Path | None:
    """Attempt dir for (task_id, n), or None when the task/attempt is missing."""
    task_dir = TaskIndex(state.fleet_home).find(task_id)
    if task_dir is None:
        return None
    adir = attempt_dir_path(task_dir, n)
    return adir if adir.is_dir() else None


@router.get("/tasks/{task_id}/attempts/{n}/summary", response_model=ContentResponse)
async def get_attempt_summary(task_id: str, n: int, state: StateDep) -> JSONResponse:
    """Derived attempt summary, rendered on demand (never stored)."""
    task_dir = TaskIndex(state.fleet_home).find(task_id)
    attempt_dir = _attempt_dir(task_id, n, state)
    if task_dir is None or attempt_dir is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    try:
        content = render_markdown(summarize(task_dir, n))
    except (OSError, ValueError):
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse({"content": content})


@router.get("/tasks/{task_id}/attempts/{n}/state", response_model=ContentResponse)
async def get_attempt_state(task_id: str, n: int, state: StateDep) -> JSONResponse:
    """STATE.md snapshot taken at reap for one attempt."""
    attempt_dir = _attempt_dir(task_id, n, state)
    if attempt_dir is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    f = attempt_state_snapshot(attempt_dir)
    if f is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse({"content": f.read_text(encoding="utf-8")})


@router.get("/tasks/{task_id}/attempts/{n}/prompt", response_model=ContentResponse)
async def get_attempt_prompt(task_id: str, n: int, state: StateDep) -> JSONResponse:
    """Recorded prompt.md for one attempt."""
    attempt_dir = _attempt_dir(task_id, n, state)
    if attempt_dir is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    f = attempt_dir / "prompt.md"
    if not f.exists():
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse({"content": f.read_text(encoding="utf-8")})


@router.get("/tasks/{task_id}/attempts/{n}/log", response_model=ContentResponse)
async def get_attempt_log(task_id: str, n: int, state: StateDep) -> JSONResponse:
    """Raw log.jsonl for one attempt."""
    attempt_dir = _attempt_dir(task_id, n, state)
    if attempt_dir is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    f = attempt_dir / "log.jsonl"
    if not f.exists():
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse({"content": f.read_text(encoding="utf-8")})
