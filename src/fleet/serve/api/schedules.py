"""Schedule REST routes: create, edit, enable/disable, delete, run now, history.

Thin handlers (ADR 0006 rule 3): parse the body, call `schedules.*`, format
the view. Every blocking call (store I/O, `bd`, the queue) runs in a sync
helper via `asyncio.to_thread`. Called by serve/app.py through ROUTERS; the
UI schedules page reads these.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from fleet.beads import client as beads_client
from fleet.beads.client import BdError
from fleet.coders import get_coder
from fleet.schedules import cron, firing
from fleet.schedules.model import OverlapPolicy, Schedule, Trigger, new_id
from fleet.schedules.store import ScheduleStore
from fleet.serve.api.models import (
    CronPreviewResponse,
    OkResponse,
    ScheduleDetail,
    ScheduleListResponse,
    ScheduleRequest,
    ScheduleRunResponse,
    ScheduleView,
)
from fleet.serve.auth import HTTP_AUTH
from fleet.serve.errors import bad_gateway, not_found, parse_json_body, unprocessable
from fleet.serve.state import StateDep

router = APIRouter(prefix="/api", dependencies=[HTTP_AUTH])

_DETAIL_LIMIT = 100
_UPCOMING_COUNT = 5
_MIN_PRIORITY = 0
_MAX_PRIORITY = 4


def _run_view(
    run: Any, task_status: str | None = None, task_title: str | None = None
) -> dict[str, Any]:
    """One run row plus the task it opened (nulls when gone)."""
    return {
        "schedule_id": run.schedule_id,
        "n": run.n,
        "scheduled_for": run.scheduled_for,
        "fired_at": run.fired_at,
        "trigger": run.trigger.value,
        "task_id": run.task_id,
        "skipped": run.skipped,
        "reason": run.reason,
        "task_status": task_status,
        "task_title": task_title,
    }


def _schedule_view(schedule: Schedule, store: ScheduleStore, now: datetime) -> dict[str, Any]:
    """One schedule plus next firing, run count, latest run (unenriched)."""
    last = store.last_run(schedule.id)
    last_cron = store.last_run(schedule.id, Trigger.cron)
    due = firing.next_due(schedule, last_cron, now)
    return {
        **schedule.to_dict(),
        "overlap": schedule.overlap.value,
        "next_fire_at": due.isoformat() if due is not None else None,
        "run_count": store.run_count(schedule.id),
        "last_run": _run_view(last) if last is not None else None,
    }


def _validated(body: Any, *, schedule_id: str, created_at: str, now: datetime) -> Schedule:
    """Build a Schedule from a JSON body, raising 422 naming the bad field."""
    if not isinstance(body, dict):
        raise unprocessable("schedule body must be a JSON object")
    try:
        req = ScheduleRequest.model_validate(body)
    except ValidationError as exc:
        raise unprocessable(str(exc)) from exc
    if not req.name.strip():
        raise unprocessable("name: required and must not be empty")
    if not req.title.strip():
        raise unprocessable("title: required and must not be empty")
    try:
        cron.parse(req.cron)
    except cron.CronError as exc:
        raise unprocessable(f"cron: {exc}") from exc
    try:
        cron.zone(req.timezone)
    except cron.CronError as exc:
        raise unprocessable(f"timezone: {exc}") from exc
    if req.coder is not None:
        try:
            get_coder(req.coder)
        except ValueError as exc:
            raise unprocessable(f"coder: {exc}") from exc
    cwd = req.cwd or None
    if cwd is not None and not Path(cwd).is_dir():
        raise unprocessable(f"cwd: not an existing directory: {cwd!r}")
    if not _MIN_PRIORITY <= req.priority <= _MAX_PRIORITY:
        raise unprocessable(f"priority: must be 0-4, got {req.priority}")
    try:
        overlap = OverlapPolicy(req.overlap)
    except ValueError:
        raise unprocessable(f"overlap: unknown policy {req.overlap!r}") from None
    return Schedule(
        id=schedule_id,
        name=req.name,
        cron=req.cron,
        timezone=req.timezone,
        enabled=req.enabled,
        title=req.title,
        description=req.description,
        cwd=cwd,
        coder=req.coder,
        model=req.model,
        priority=req.priority,
        overlap=overlap,
        created_at=created_at,
        updated_at=now.isoformat(),
    )


def _create(fleet_home: Path, body: Any, now: datetime) -> dict[str, Any]:
    """Validate, save with a fresh id, and return the view (runs in a thread)."""
    store = ScheduleStore(fleet_home)
    moment = now.isoformat()
    schedule = _validated(body, schedule_id=new_id(), created_at=moment, now=now)
    store.save(schedule)
    return _schedule_view(schedule, store, now)


def _list(fleet_home: Path, now: datetime) -> dict[str, Any]:
    """All schedules with next firing, run count, latest run (runs in a thread)."""
    store = ScheduleStore(fleet_home)
    return {"schedules": [_schedule_view(item, store, now) for item in store.list()]}


def _task_map(schedule_id: str, items: Any) -> dict[str, tuple[Any, Any]]:
    """Bead id to (status, title) for this schedule's tasks."""
    out: dict[str, tuple[Any, Any]] = {}
    rows = items if isinstance(items, list) else []
    for item in rows:
        if not isinstance(item, dict):
            continue
        meta = item.get("metadata")
        if isinstance(meta, dict) and meta.get("fleet_schedule_id") not in (None, schedule_id):
            continue
        task_id = item.get("id")
        if task_id:
            out[task_id] = (item.get("status"), item.get("title"))
    return out


def _detail(fleet_home: Path, schedule_id: str, now: datetime) -> dict[str, Any] | None:
    """One schedule with 5 upcoming firings and enriched runs (runs in a thread)."""
    store = ScheduleStore(fleet_home)
    schedule = store.get(schedule_id)
    if schedule is None:
        return None
    try:
        items = beads_client.run_json(
            [
                "list",
                "--all",
                "--limit",
                "0",
                "--metadata-field",
                f"fleet_schedule_id={schedule_id}",
            ],
            cwd=fleet_home,
        )
    except BdError:
        items = []
    mapping = _task_map(schedule_id, items)
    runs = [
        _run_view(run, *mapping.get(run.task_id or "", (None, None)))
        for run in store.runs(schedule_id, limit=_DETAIL_LIMIT)
    ]
    view = _schedule_view(schedule, store, now)
    view["last_run"] = runs[0] if runs else None
    fires = cron.upcoming(schedule.cron, now, _UPCOMING_COUNT, schedule.timezone)
    view["upcoming"] = [fire.isoformat() for fire in fires]
    view["runs"] = runs
    return view


def _update(fleet_home: Path, schedule_id: str, body: Any, now: datetime) -> dict[str, Any] | None:
    """Validate and rewrite a schedule, keeping id/created_at (runs in a thread)."""
    store = ScheduleStore(fleet_home)
    existing = store.get(schedule_id)
    if existing is None:
        return None
    schedule = _validated(body, schedule_id=schedule_id, created_at=existing.created_at, now=now)
    store.save(schedule)
    return _schedule_view(schedule, store, now)


def _delete(fleet_home: Path, schedule_id: str) -> bool:
    """Remove a schedule and its run history (runs in a thread)."""
    return ScheduleStore(fleet_home).delete(schedule_id)


def _set_enabled(fleet_home: Path, schedule_id: str, enabled: bool, now: datetime) -> bool:
    """Flip a schedule's enabled flag, bumping updated_at (runs in a thread)."""
    store = ScheduleStore(fleet_home)
    existing = store.get(schedule_id)
    if existing is None:
        return False
    store.save(replace(existing, enabled=enabled, updated_at=now.isoformat()))
    return True


def _run_now(fleet_home: Path, queue: Any, schedule_id: str, now: datetime) -> Any:
    """Fire one manual run; None when unknown, BdError as bad_gateway (in a thread)."""
    store = ScheduleStore(fleet_home)
    schedule = store.get(schedule_id)
    if schedule is None:
        return None
    try:
        run = firing.fire(schedule, store=store, queue=queue, now=now, trigger=Trigger.manual)
    except BdError as exc:
        raise bad_gateway(str(exc) or "queue failed") from exc
    status: str | None = None
    title: str | None = None
    if run.task_id is not None:
        try:
            task = queue.get(run.task_id)
        except BdError:
            task = None
        if task is not None:
            status, title = task.status, task.title
    return _run_view(run, status, title)


def _preview(body: Any, now: datetime) -> dict[str, Any]:
    """Cron validity plus upcoming firings; a bad expression is valid=false, never 4xx."""
    payload = body if isinstance(body, dict) else {}
    text = str(payload.get("cron", "") or "")
    timezone = str(payload.get("timezone", "UTC") or "UTC")
    try:
        count = max(1, min(int(payload.get("count", _UPCOMING_COUNT)), 50))
    except (TypeError, ValueError):
        count = _UPCOMING_COUNT
    try:
        cron.parse(text)
        cron.zone(timezone)
    except cron.CronError as exc:
        return {"valid": False, "error": str(exc), "upcoming": []}
    try:
        fires = cron.upcoming(text, now, count, timezone)
    except cron.CronError as exc:
        return {"valid": False, "error": str(exc), "upcoming": []}
    return {"valid": True, "error": None, "upcoming": [fire.isoformat() for fire in fires]}


@router.get("/schedules", response_model=ScheduleListResponse)
async def list_schedules(state: StateDep) -> JSONResponse:
    """Every schedule with next firing, run count and latest run."""
    payload = await asyncio.to_thread(_list, state.fleet_home, datetime.now(UTC))
    return JSONResponse(payload)


@router.post("/schedules", response_model=ScheduleView)
async def create_schedule(request: Request, state: StateDep) -> JSONResponse:
    """Validate and save a schedule; 201 with the view."""
    body = await parse_json_body(request)
    payload = await asyncio.to_thread(_create, state.fleet_home, body, datetime.now(UTC))
    return JSONResponse(payload, status_code=201)


@router.post("/schedules/preview", response_model=CronPreviewResponse)
async def preview_cron(request: Request) -> JSONResponse:
    """Live cron check for the form; a bad expression is valid=false."""
    return JSONResponse(_preview(await parse_json_body(request), datetime.now(UTC)))


@router.get("/schedules/{schedule_id}", response_model=ScheduleDetail)
async def get_schedule(schedule_id: str, state: StateDep) -> JSONResponse:
    """One schedule with upcoming firings and enriched run history."""
    payload = await asyncio.to_thread(_detail, state.fleet_home, schedule_id, datetime.now(UTC))
    if payload is None:
        raise not_found("schedule", schedule_id)
    return JSONResponse(payload)


@router.put("/schedules/{schedule_id}", response_model=ScheduleView)
async def update_schedule(schedule_id: str, request: Request, state: StateDep) -> JSONResponse:
    """Validate and rewrite a schedule, keeping id and created_at."""
    body = await parse_json_body(request)
    payload = await asyncio.to_thread(
        _update, state.fleet_home, schedule_id, body, datetime.now(UTC)
    )
    if payload is None:
        raise not_found("schedule", schedule_id)
    return JSONResponse(payload)


@router.delete("/schedules/{schedule_id}", response_model=OkResponse)
async def delete_schedule(schedule_id: str, state: StateDep) -> JSONResponse:
    """Remove a schedule and its run history."""
    removed = await asyncio.to_thread(_delete, state.fleet_home, schedule_id)
    if not removed:
        raise not_found("schedule", schedule_id)
    return JSONResponse({"ok": True})


@router.post("/schedules/{schedule_id}/run", response_model=ScheduleRunResponse)
async def run_schedule(schedule_id: str, state: StateDep) -> JSONResponse:
    """Fire one manual run now and return it with the new task id."""
    payload = await asyncio.to_thread(
        _run_now, state.fleet_home, state.queue, schedule_id, datetime.now(UTC)
    )
    if payload is None:
        raise not_found("schedule", schedule_id)
    return JSONResponse({"run": payload})


@router.post("/schedules/{schedule_id}/enable", response_model=OkResponse)
async def enable_schedule(schedule_id: str, state: StateDep) -> JSONResponse:
    """Enable a schedule without resending the full body."""
    enabled = await asyncio.to_thread(
        _set_enabled, state.fleet_home, schedule_id, True, datetime.now(UTC)
    )
    if not enabled:
        raise not_found("schedule", schedule_id)
    return JSONResponse({"ok": True})


@router.post("/schedules/{schedule_id}/disable", response_model=OkResponse)
async def disable_schedule(schedule_id: str, state: StateDep) -> JSONResponse:
    """Disable a schedule without resending the full body."""
    disabled = await asyncio.to_thread(
        _set_enabled, state.fleet_home, schedule_id, False, datetime.now(UTC)
    )
    if not disabled:
        raise not_found("schedule", schedule_id)
    return JSONResponse({"ok": True})
