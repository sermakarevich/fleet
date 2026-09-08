"""Beads portal REST routes.

Unlike `/api/tasks` (which enumerates fleet task dirs and overlays beads status),
these endpoints are a direct portal into the beads DB at ``fleet_home()``: list
every bead, inspect one (description, notes, dependencies, comments), and manage
it (change status, unblock, remove assignee). All mutations shell out to ``bd``.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from fleet.beads import client as beads_client
from fleet.beads.client import BdError
from fleet.serve.api.models import (
    BeadDetail,
    BeadListResponse,
    OkResponse,
)
from fleet.serve.api.task_summary import beads_assignee_clearer
from fleet.state import task_actions
from fleet.state.paths import fleet_home as get_fleet_home

router = APIRouter(prefix="/api")

# Statuses beads accepts via `bd update --status`. Used to reject arbitrary input.
VALID_STATUSES = {"open", "in_progress", "blocked", "deferred", "closed", "pinned", "hooked"}


def _summary(item: dict) -> dict:
    return {
        "id": item.get("id"),
        "title": item.get("title"),
        "status": item.get("status"),
        "priority": item.get("priority"),
        "issue_type": item.get("issue_type"),
        "assignee": item.get("assignee"),
        "created_at": item.get("created_at"),
        "updated_at": item.get("updated_at"),
        "closed_at": item.get("closed_at"),
        "dependency_count": item.get("dependency_count"),
        "dependent_count": item.get("dependent_count"),
        "comment_count": item.get("comment_count"),
    }


def _detail(body: dict) -> dict:
    deps = [
        {
            "id": d.get("id"),
            "title": d.get("title"),
            "status": d.get("status"),
            "dependency_type": d.get("dependency_type"),
        }
        for d in (body.get("dependencies") or [])
        if isinstance(d, dict)
    ]
    comments = [
        {
            "id": c.get("id"),
            "author": c.get("author"),
            "text": c.get("text"),
            "created_at": c.get("created_at"),
        }
        for c in (body.get("comments") or [])
        if isinstance(c, dict)
    ]
    return {
        "id": body.get("id"),
        "title": body.get("title"),
        "status": body.get("status"),
        "priority": body.get("priority"),
        "issue_type": body.get("issue_type"),
        "assignee": body.get("assignee"),
        "description": body.get("description"),
        "notes": body.get("notes"),
        "created_at": body.get("created_at"),
        "updated_at": body.get("updated_at"),
        "closed_at": body.get("closed_at"),
        "close_reason": body.get("close_reason"),
        "dependencies": deps,
        "comments": comments,
    }


async def _update(bead_id: str, extra: list[str]) -> JSONResponse:
    home = get_fleet_home()
    try:
        await asyncio.to_thread(beads_client.run, ["update", bead_id, *extra], cwd=home)
    except BdError as exc:
        return JSONResponse({"error": str(exc) or "bd update failed"}, status_code=502)
    return JSONResponse({"ok": True})


@router.get("/beads", response_model=BeadListResponse)
async def list_beads() -> JSONResponse:
    """List every bead in the beads DB."""
    home = get_fleet_home()
    try:
        items = await asyncio.to_thread(beads_client.list_all, home)
    except BdError as exc:
        return JSONResponse({"error": str(exc) or "bd list failed"}, status_code=502)
    return JSONResponse({"beads": [_summary(it) for it in items if isinstance(it, dict)]})


@router.get("/beads/{bead_id}", response_model=BeadDetail)
async def get_bead(bead_id: str) -> JSONResponse:
    """One bead with description, notes, dependencies, comments."""
    home = get_fleet_home()
    try:
        body = await asyncio.to_thread(beads_client.show, bead_id, home)
    except BdError as exc:
        return JSONResponse({"error": str(exc) or "bd show failed"}, status_code=502)
    if not isinstance(body, dict):
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse(_detail(body))


@router.post("/beads/{bead_id}/status", response_model=OkResponse)
async def set_status(bead_id: str, request: Request) -> JSONResponse:
    """Set a bead status; `closed` goes through `bd close` like queue.close."""
    body = await request.json()
    status = (body or {}).get("status", "")
    if status not in VALID_STATUSES:
        return JSONResponse({"error": f"invalid status: {status!r}"}, status_code=422)
    if status == "closed":
        home = get_fleet_home()
        try:
            await asyncio.to_thread(
                beads_client.run,
                ["close", bead_id, "--reason", "closed via BD portal"],
                cwd=home,
            )
        except BdError as exc:
            return JSONResponse({"error": str(exc) or "bd close failed"}, status_code=502)
        return JSONResponse({"ok": True})
    return await _update(bead_id, ["--status", status])


@router.post("/beads/{bead_id}/unblock", response_model=OkResponse)
async def unblock_bead(bead_id: str) -> JSONResponse:
    """Reopen a bead (`bd update --status open`)."""
    return await _update(bead_id, ["--status", "open"])


@router.post("/beads/{bead_id}/remove-assignee", response_model=OkResponse)
async def remove_bead_assignee(bead_id: str) -> JSONResponse:
    """Clear the assignee; the portal targets beads, so a missing task dir is ok."""
    home = get_fleet_home()
    try:
        await asyncio.to_thread(
            task_actions.remove_assignee,
            home,
            bead_id,
            clear_assignee=beads_assignee_clearer(home),
        )
    except task_actions.TaskNotFound:
        return await _update(bead_id, ["--assignee", ""])
    except BdError as exc:
        return JSONResponse({"error": str(exc)}, status_code=502)
    return JSONResponse({"ok": True})
