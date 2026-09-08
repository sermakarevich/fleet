"""Task stream routes: logs, stderr, touched files, events (FR-17..FR-20)."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from fleet.serve.api.models import (
    ContentResponse,
    FileListResponse,
    LogListResponse,
    TaskEventsResponse,
)
from fleet.serve.api.task_summary import event_to_json, parse_log_line
from fleet.serve.state import AppState, StateDep
from fleet.state.attempts import latest_attempt_dir
from fleet.state.events import EventScanCache, iter_events, scan_cached
from fleet.state.paths import task_dir as resolve_task_dir

router = APIRouter(prefix="/api")

_events_cache = EventScanCache()


def _latest_log(task_id: str, state: AppState, filename: str) -> Path:
    task_dir = resolve_task_dir(state.home, task_id)
    attempt_dir = latest_attempt_dir(task_dir)
    if attempt_dir is not None:
        return attempt_dir / filename
    return task_dir / filename


@router.get("/tasks/{task_id}/logs", response_model=LogListResponse)
async def get_task_logs(task_id: str, state: StateDep, level: str | None = None) -> JSONResponse:
    """Parsed log.jsonl lines, optionally filtered by level (FR-17)."""
    entries: list[dict] = []
    log_file = _latest_log(task_id, state, "log.jsonl")
    if log_file.exists():
        try:
            for raw in log_file.read_text(encoding="utf-8").splitlines():
                entry = parse_log_line(raw)
                if entry is None or (level and entry.level != level):
                    continue
                entries.append(
                    {
                        "ts": entry.ts,
                        "level": entry.level,
                        "message": entry.message,
                        "extra": entry.extra,
                    }
                )
        except OSError:
            pass
    return JSONResponse({"lines": entries})


@router.get("/tasks/{task_id}/stderr", response_model=ContentResponse)
async def get_task_stderr(task_id: str, state: StateDep) -> JSONResponse:
    """Raw stderr content, empty when absent (FR-18)."""
    f = _latest_log(task_id, state, "log.stderr")
    return JSONResponse({"content": f.read_text(encoding="utf-8") if f.exists() else ""})


@router.get("/tasks/{task_id}/files", response_model=FileListResponse)
async def get_task_files(task_id: str, state: StateDep) -> JSONResponse:
    """Per-file read/edit/write counts from the event scan (FR-20)."""
    counts = scan_cached(resolve_task_dir(state.home, task_id), _events_cache).files_touched
    files = [
        {"path": path, "read": fc.read, "edit": fc.edit, "write": fc.write}
        for path, fc in sorted(counts.items())
    ]
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
    task_dir = resolve_task_dir(state.home, task_id)
    if not task_dir.is_dir():
        return JSONResponse({"error": "not found"}, status_code=404)
    allow_kinds = {k.strip() for k in kind.split(",") if k.strip()} if kind else None
    rows = [
        row
        for row in iter_events(task_dir)
        if allow_kinds is None or row.get("kind", "") in allow_kinds
    ]
    total = len(rows)
    start = max(0, total - limit) if offset is None else max(0, offset)
    page = [event_to_json(row, start + i) for i, row in enumerate(rows[start : start + limit])]
    return JSONResponse({"total": total, "offset": start, "events": page})
