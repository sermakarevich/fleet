"""Single-task routes: detail, children, attempts index (FR-07, FR-11)."""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from fleet.beads import client as beads_client
from fleet.beads.client import BdError
from fleet.serve.api.task_summary import build_summary, fetch_beads_info
from fleet.serve.state import AppState, StateDep
from fleet.state.paths import task_dir as resolve_task_dir
from fleet.state.task_index import TaskIndex
from fleet.state.task_summary import read_result

router = APIRouter(prefix="/api")


@router.get("/tasks/{task_id}")
async def get_task(task_id: str, state: StateDep) -> JSONResponse:
    """One task summary, overlaid with beads status/priority/depends_on."""
    index = TaskIndex(state.home)
    task_dir = index.find(task_id)
    if task_dir is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    data = index.read_raw(task_id) or {}
    beads_info = await asyncio.to_thread(fetch_beads_info, task_id, state.home)
    if beads_info is not None:
        data = {**data, **beads_info}
    return JSONResponse(build_summary(task_dir, data, state.home))


@router.get("/tasks/{task_id}/attempts")
async def list_task_attempts(task_id: str, state: StateDep) -> JSONResponse:
    """Attempt timeline for one task, derived from attempts.jsonl."""
    index = TaskIndex(state.home)
    task_dir = index.find(task_id)
    if task_dir is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    summary = build_summary(task_dir, index.read_raw(task_id) or {}, state.home)
    return JSONResponse({"attempts": summary["attempts"]})


@router.get("/tasks/{task_id}/children")
async def get_task_children(task_id: str, state: StateDep) -> JSONResponse:
    """Children panel for epics: child id/status/RESULT plus CHILDREN.md."""
    index = TaskIndex(state.home)
    task_dir = index.find(task_id)
    if task_dir is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    try:
        deps = await asyncio.to_thread(beads_client.children_of, task_id, state.home)
    except BdError as exc:
        return JSONResponse({"error": str(exc)}, status_code=422)
    children = [_child_row(dep, state) for dep in deps if _has_id(dep)]
    children_md = _read_children_md(task_dir / "artifacts" / "CHILDREN.md")
    return JSONResponse({"children": children, "children_md": children_md})


def _read_children_md(digest_file: Path) -> str | None:
    if not digest_file.exists():
        return None
    try:
        return digest_file.read_text(encoding="utf-8")
    except OSError:
        return None


def _has_id(dep: object) -> bool:
    return isinstance(dep, dict) and bool(dep.get("id"))


def _child_row(dep: dict, state: AppState) -> dict:
    cid = str(dep["id"])
    declared = read_result(resolve_task_dir(state.home, cid))
    return {
        "id": cid,
        "title": dep.get("title"),
        "status": dep.get("status"),
        "result_status": (declared or {}).get("status"),
        "result_summary": (declared or {}).get("summary"),
    }
