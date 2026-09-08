"""Task mutation routes: kill, requeue, unblock, queue ops, remove-assignee."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from fleet.beads.client import BdError
from fleet.observability.process import service_status
from fleet.serve.api.task_summary import beads_assignee_clearer, body_note, resolve_status
from fleet.serve.state import AppState, StateDep
from fleet.state import task_actions
from fleet.state.task_index import TaskIndex

router = APIRouter(prefix="/api")


def _missing(task_id: str, state: AppState) -> JSONResponse | None:
    if TaskIndex(state.home).find(task_id) is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    return None


async def _queue_call(task_id: str, state: AppState, method: str) -> JSONResponse:
    if (missing := _missing(task_id, state)) is not None:
        return missing
    try:
        await asyncio.to_thread(getattr(state.queue, method), task_id)
    except BdError as exc:
        return JSONResponse({"error": str(exc)}, status_code=422)
    return JSONResponse({"ok": True})


@router.post("/tasks/{task_id}/kill")
async def kill_task(task_id: str, state: StateDep) -> JSONResponse:
    """Signal a running task (.kill) or close a queued one via the queue."""
    if (missing := _missing(task_id, state)) is not None:
        return missing
    status = await asyncio.to_thread(resolve_status, task_id, state.home)
    running = service_status("supervisor", state.home).alive
    try:
        outcome = await asyncio.to_thread(
            task_actions.kill,
            state.home,
            state.queue,
            task_id,
            status=status,
            supervisor_running=running,
        )
    except task_actions.TaskNotFound:
        return JSONResponse({"error": "not found"}, status_code=404)
    except BdError as exc:
        return JSONResponse({"error": str(exc)}, status_code=422)
    return JSONResponse({"ok": True, "result": outcome})


@router.post("/tasks/{task_id}/requeue")
async def requeue_task(task_id: str, state: StateDep) -> JSONResponse:
    """Release a task back to the queue."""
    try:
        await asyncio.to_thread(state.queue.release, task_id)
    except BdError as exc:
        return JSONResponse({"error": str(exc)}, status_code=422)
    return JSONResponse({"ok": True})


@router.post("/tasks/{task_id}/unblock")
async def unblock_task(task_id: str, request: Request, state: StateDep) -> JSONResponse:
    """Release a blocked task, clear retry state, journal the note."""
    note = await body_note(request)
    try:
        await asyncio.to_thread(task_actions.unblock, state.home, state.queue, task_id, note)
    except task_actions.TaskNotFound:
        return JSONResponse({"error": "not found"}, status_code=404)
    except BdError as exc:
        return JSONResponse({"error": str(exc)}, status_code=422)
    return JSONResponse({"ok": True})


@router.post("/tasks/{task_id}/unignore")
async def unignore_task(task_id: str, state: StateDep) -> JSONResponse:
    """Clear a task's triage ignore."""
    return await _queue_call(task_id, state, "clear_ignore")


@router.post("/tasks/{task_id}/close")
async def close_task(task_id: str, state: StateDep) -> JSONResponse:
    """Close a task via the queue."""
    return await _queue_call(task_id, state, "close")


@router.delete("/tasks/{task_id}")
async def delete_task(task_id: str, state: StateDep) -> JSONResponse:
    """Delete a task via the queue."""
    return await _queue_call(task_id, state, "delete")


@router.post("/tasks/{task_id}/remove-assignee")
async def remove_assignee(task_id: str, state: StateDep) -> JSONResponse:
    """Clear the beads assignee and the task.json coder mirror."""
    try:
        await asyncio.to_thread(
            task_actions.remove_assignee,
            state.home,
            task_id,
            clear_assignee=beads_assignee_clearer(state.home),
        )
    except task_actions.TaskNotFound:
        return JSONResponse({"error": "not found"}, status_code=404)
    except BdError as exc:
        return JSONResponse({"error": str(exc)}, status_code=422)
    return JSONResponse({"ok": True})
