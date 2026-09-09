"""Per-attempt routes: one artifact table, one handler (summary/prompt/state/log)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from fleet.serve.api.models import ContentResponse
from fleet.serve.auth import HTTP_AUTH
from fleet.serve.errors import not_found
from fleet.serve.state import AppState, StateDep
from fleet.state.attempt_summary import render_markdown, summarize
from fleet.state.legacy_task_dir import attempt_state_snapshot
from fleet.state.paths import attempt_dir
from fleet.state.task_index import TaskIndex

router = APIRouter(prefix="/api", dependencies=[HTTP_AUTH])


def _attempt_dir(task_id: str, attempt_no: int, state: AppState) -> Path | None:
    """Attempt dir for (task_id, attempt_no), or None when the task/attempt is missing."""
    task_dir = TaskIndex(state.fleet_home).find(task_id)
    if task_dir is None:
        return None
    adir = attempt_dir(task_dir, attempt_no)
    return adir if adir.is_dir() else None


def _read_text_or_none(path: Path) -> str | None:
    """File text, None when missing/unreadable (runs in a thread)."""
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _summary_content(attempt_path: Path) -> str | None:
    """Derived attempt summary markdown (never stored; runs in a thread)."""
    try:
        attempt_no = int(attempt_path.name)
    except ValueError:
        return None
    try:
        return render_markdown(summarize(attempt_path.parent.parent, attempt_no))
    except (OSError, ValueError):
        return None


def _prompt_content(attempt_path: Path) -> str | None:
    """Recorded prompt.md for one attempt (runs in a thread)."""
    return _read_text_or_none(attempt_path / "prompt.md")


def _state_content(attempt_path: Path) -> str | None:
    """STATE.md snapshot taken at reap for one attempt (runs in a thread)."""
    snapshot = attempt_state_snapshot(attempt_path)
    return _read_text_or_none(snapshot) if snapshot is not None else None


def _log_content(attempt_path: Path) -> str | None:
    """Raw log.jsonl for one attempt (runs in a thread)."""
    return _read_text_or_none(attempt_path / "log.jsonl")


#: Attempt artifact name → content reader (attempt dir → text or None when
#: missing). One table, not an if-chain; summary is derived on demand while
#: the rest are files, so the table reads content rather than paths.
ARTIFACTS: dict[str, Callable[[Path], str | None]] = {
    "summary": _summary_content,
    "state": _state_content,
    "prompt": _prompt_content,
    "log": _log_content,
}


@router.get("/tasks/{task_id}/attempts/{attempt_no}/{artifact}", response_model=ContentResponse)
async def get_attempt_artifact(
    task_id: str, attempt_no: int, artifact: str, state: StateDep
) -> JSONResponse:
    """One attempt artifact by name; 404 for unknown names or missing files."""
    reader = ARTIFACTS.get(artifact)
    if reader is None:
        raise not_found("artifact", artifact)
    attempt_path = _attempt_dir(task_id, attempt_no, state)
    if attempt_path is None:
        raise not_found("attempt", f"{task_id}#{attempt_no}")
    content = await asyncio.to_thread(reader, attempt_path)
    if content is None:
        raise not_found("artifact", artifact)
    return JSONResponse({"content": content})
