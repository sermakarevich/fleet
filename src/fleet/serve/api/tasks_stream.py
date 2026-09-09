"""Task stream routes: logs, stderr, touched files, events (FR-17..FR-20)."""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from fleet.serve.api.artifact_files import read_text_or_empty
from fleet.serve.api.models import (
    ContentResponse,
    FileListResponse,
    LogListResponse,
    TaskEventsResponse,
)
from fleet.serve.api.stream_reads import events_page, files_payload, read_log_entries
from fleet.serve.state import AppState, StateDep
from fleet.state.attempts import latest_attempt_dir
from fleet.state.paths import task_dir as resolve_task_dir

router = APIRouter(prefix="/api")


def _latest_log(task_id: str, state: AppState, filename: str) -> Path:
    task_dir = resolve_task_dir(state.fleet_home, task_id)
    attempt_dir = latest_attempt_dir(task_dir)
    if attempt_dir is not None:
        return attempt_dir / filename
    return task_dir / filename


@router.get("/tasks/{task_id}/logs", response_model=LogListResponse)
async def get_task_logs(task_id: str, state: StateDep, level: str | None = None) -> JSONResponse:
    """Parsed log.jsonl lines, optionally filtered by level (FR-17)."""
    log_file = _latest_log(task_id, state, "log.jsonl")
    entries = await asyncio.to_thread(read_log_entries, log_file, level)
    return JSONResponse({"lines": entries})


@router.get("/tasks/{task_id}/stderr", response_model=ContentResponse)
async def get_task_stderr(task_id: str, state: StateDep) -> JSONResponse:
    """Raw stderr content, empty when absent (FR-18)."""
    f = _latest_log(task_id, state, "log.stderr")
    return JSONResponse({"content": await asyncio.to_thread(read_text_or_empty, f)})


@router.get("/tasks/{task_id}/files", response_model=FileListResponse)
async def get_task_files(task_id: str, state: StateDep) -> JSONResponse:
    """Per-file read/edit/write counts from the event scan (FR-20)."""
    task_path = resolve_task_dir(state.fleet_home, task_id)
    files = await asyncio.to_thread(files_payload, task_path)
    return JSONResponse({"files": files})


@router.get("/tasks/{task_id}/events", response_model=TaskEventsResponse)
async def get_task_events(
    task_id: str,
    state: StateDep,
    offset: int | None = None,
    limit: int = 100,
    kind: str | None = None,
) -> JSONResponse:
    """Whole-task event history across attempts, paged (tail by default)."""
    task_dir = resolve_task_dir(state.fleet_home, task_id)
    if not task_dir.is_dir():
        return JSONResponse({"error": "not found"}, status_code=404)
    allow_kinds = {k.strip() for k in kind.split(",") if k.strip()} if kind else None
    page = await asyncio.to_thread(events_page, task_dir, offset, limit, allow_kinds)
    return JSONResponse(page)
