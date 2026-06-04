"""Beads portal REST routes.

Unlike `/api/tasks` (which enumerates fleet task dirs and overlays beads status),
these endpoints are a direct portal into the beads DB at ``fleet_home()``: list
every bead, inspect one (description, notes, dependencies, comments), and manage
it (change status, unblock, remove assignee). All mutations shell out to ``bd``.
"""
from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from fleet.serve.stats import fleet_home as get_fleet_home

# Statuses beads accepts via `bd update --status`. Used to reject arbitrary input.
VALID_STATUSES = {"open", "in_progress", "blocked", "deferred", "closed", "pinned", "hooked"}


def _run_bd(args: list[str], home: Path) -> tuple[int, str, str]:
    """Run a `bd` subcommand with cwd=home. Returns (returncode, stdout, stderr)."""
    try:
        result = subprocess.run(
            ["bd", *args],
            capture_output=True,
            text=True,
            cwd=home,
        )
    except FileNotFoundError:
        return 127, "", "bd executable not found"
    return result.returncode, result.stdout, result.stderr


def _parse_bd_json(stdout: str):
    """Parse `bd --json` output, unwrapping the optional {data: ...} envelope."""
    data = json.loads(stdout)
    if isinstance(data, dict) and "data" in data:
        return data["data"]
    return data


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


def create_beads_router() -> APIRouter:
    router = APIRouter(prefix="/api")

    async def _update(bead_id: str, extra: list[str]) -> JSONResponse:
        home = get_fleet_home()
        rc, _out, err = await asyncio.to_thread(_run_bd, ["update", bead_id, *extra], home)
        if rc != 0:
            return JSONResponse({"error": err.strip() or "bd update failed"}, status_code=502)
        return JSONResponse({"ok": True})

    @router.get("/beads")
    async def list_beads() -> JSONResponse:
        home = get_fleet_home()
        rc, out, err = await asyncio.to_thread(
            _run_bd, ["list", "--all", "--json", "--limit", "0"], home
        )
        if rc != 0:
            return JSONResponse({"error": err.strip() or "bd list failed"}, status_code=502)
        try:
            items = _parse_bd_json(out) if out.strip() else []
        except json.JSONDecodeError as exc:
            return JSONResponse({"error": f"could not parse bd output: {exc}"}, status_code=502)
        if not isinstance(items, list):
            items = []
        beads = [_summary(it) for it in items if isinstance(it, dict)]
        return JSONResponse({"beads": beads})

    @router.get("/beads/{bead_id}")
    async def get_bead(bead_id: str) -> JSONResponse:
        home = get_fleet_home()
        rc, out, err = await asyncio.to_thread(_run_bd, ["show", bead_id, "--json"], home)
        if rc != 0:
            return JSONResponse({"error": err.strip() or "bd show failed"}, status_code=502)
        try:
            body = _parse_bd_json(out) if out.strip() else None
        except json.JSONDecodeError as exc:
            return JSONResponse({"error": f"could not parse bd output: {exc}"}, status_code=502)
        if isinstance(body, list):
            body = body[0] if body else None
        if not isinstance(body, dict):
            return JSONResponse({"error": "not found"}, status_code=404)
        return JSONResponse(_detail(body))

    @router.post("/beads/{bead_id}/status")
    async def set_status(bead_id: str, request: Request) -> JSONResponse:
        body = await request.json()
        status = (body or {}).get("status", "")
        if status not in VALID_STATUSES:
            return JSONResponse({"error": f"invalid status: {status!r}"}, status_code=422)
        # `closed` is special in beads: it records close_reason/closed_at and is done
        # via `bd close` (mirroring queue.close), not `bd update --status closed`.
        if status == "closed":
            home = get_fleet_home()
            rc, _out, err = await asyncio.to_thread(
                _run_bd, ["close", bead_id, "--reason", "closed via BD portal"], home
            )
            if rc != 0:
                return JSONResponse({"error": err.strip() or "bd close failed"}, status_code=502)
            return JSONResponse({"ok": True})
        return await _update(bead_id, ["--status", status])

    @router.post("/beads/{bead_id}/unblock")
    async def unblock_bead(bead_id: str) -> JSONResponse:
        return await _update(bead_id, ["--status", "open"])

    @router.post("/beads/{bead_id}/remove-assignee")
    async def remove_bead_assignee(bead_id: str) -> JSONResponse:
        return await _update(bead_id, ["--assignee", ""])

    return router
