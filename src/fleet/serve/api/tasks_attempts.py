"""Per-attempt routes: derived summary, prompt, state snapshot, log."""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from fleet.serve.api.models import ContentResponse
from fleet.serve.state import AppState, StateDep
from fleet.state.attempt_summary import render_markdown, summarize
from fleet.state.legacy_task_dir import attempt_state_snapshot
from fleet.state.paths import attempt_dir
from fleet.state.task_index import TaskIndex

router = APIRouter(prefix="/api")


def _attempt_dir(task_id: str, attempt_no: int, state: AppState) -> Path | None:
    """Attempt dir for (task_id, attempt_no), or None when the task/attempt is missing."""
    task_dir = TaskIndex(state.fleet_home).find(task_id)
    if task_dir is None:
        return None
    adir = attempt_dir(task_dir, attempt_no)
    return adir if adir.is_dir() else None


def _read_text_or_none(path: Path) -> str | None:
    """File text, None when missing/unreadable (runs in a thread)."""
    if not path.exists():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _render_attempt_summary(task_dir: Path, attempt_no: int) -> str:
    """Derived attempt summary markdown (runs in a thread; reads files)."""
    return render_markdown(summarize(task_dir, attempt_no))


@router.get("/tasks/{task_id}/attempts/{attempt_no}/summary", response_model=ContentResponse)
async def get_attempt_summary(task_id: str, attempt_no: int, state: StateDep) -> JSONResponse:
    """Derived attempt summary, rendered on demand (never stored)."""
    task_dir = TaskIndex(state.fleet_home).find(task_id)
    attempt_path = _attempt_dir(task_id, attempt_no, state)
    if task_dir is None or attempt_path is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    try:
        content = await asyncio.to_thread(_render_attempt_summary, task_dir, attempt_no)
    except (OSError, ValueError):
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse({"content": content})


@router.get("/tasks/{task_id}/attempts/{attempt_no}/state", response_model=ContentResponse)
async def get_attempt_state(task_id: str, attempt_no: int, state: StateDep) -> JSONResponse:
    """STATE.md snapshot taken at reap for one attempt."""
    attempt_path = _attempt_dir(task_id, attempt_no, state)
    if attempt_path is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    f = attempt_state_snapshot(attempt_path)
    if f is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    content = await asyncio.to_thread(_read_text_or_none, f)
    if content is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse({"content": content})


@router.get("/tasks/{task_id}/attempts/{attempt_no}/prompt", response_model=ContentResponse)
async def get_attempt_prompt(task_id: str, attempt_no: int, state: StateDep) -> JSONResponse:
    """Recorded prompt.md for one attempt."""
    attempt_path = _attempt_dir(task_id, attempt_no, state)
    if attempt_path is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    content = await asyncio.to_thread(_read_text_or_none, attempt_path / "prompt.md")
    if content is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse({"content": content})


@router.get("/tasks/{task_id}/attempts/{attempt_no}/log", response_model=ContentResponse)
async def get_attempt_log(task_id: str, attempt_no: int, state: StateDep) -> JSONResponse:
    """Raw log.jsonl for one attempt."""
    attempt_path = _attempt_dir(task_id, attempt_no, state)
    if attempt_path is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    content = await asyncio.to_thread(_read_text_or_none, attempt_path / "log.jsonl")
    if content is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse({"content": content})
