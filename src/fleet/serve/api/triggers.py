"""Trigger REST routes: create, edit, enable/disable, delete, preview.

Thin handlers (ADR 0006 rule 3): parse the body, call `triggers.*`, format
the view. Every blocking call (store I/O, the queue) runs in a sync helper
via `asyncio.to_thread`. Called by serve/app.py through ROUTERS; the UI
triggers page reads these.
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

from fleet.coders import get_coder
from fleet.serve.api.models import (
    OkResponse,
    SourceListResponse,
    TriggerDetail,
    TriggerListResponse,
    TriggerPreviewResponse,
    TriggerRequest,
    TriggerView,
)
from fleet.serve.auth import HTTP_AUTH
from fleet.serve.errors import not_found, parse_json_body, unprocessable
from fleet.serve.state import StateDep
from fleet.triggers import firing as firing_mod
from fleet.triggers.model import Trigger, new_id
from fleet.triggers.sources import SOURCES, UnknownSource, source_for, source_params
from fleet.triggers.sources.base import SourceContext
from fleet.triggers.store import TriggerStore

router = APIRouter(prefix="/api", dependencies=[HTTP_AUTH])

_DETAIL_LIMIT = 100
_MIN_PRIORITY = 0
_MAX_PRIORITY = 4


def _trigger_view(trigger: Trigger, store: TriggerStore) -> dict[str, Any]:
    """One trigger plus firing count and latest firing time."""
    last = store.last_firing(trigger.id)
    return {
        **trigger.to_dict(),
        "target": trigger.target.value,
        "firing_count": store.firing_count(trigger.id),
        "last_fired_at": last.fired_at if last is not None else None,
    }


def _validated(
    fleet_home: Path, body: Any, *, trigger_id: str, created_at: str, now: datetime
) -> Trigger:
    """Build a Trigger from a JSON body, raising 422 naming the bad field."""
    _ = fleet_home
    if not isinstance(body, dict):
        raise unprocessable("trigger body must be a JSON object")
    try:
        req = TriggerRequest.model_validate(body)
    except ValidationError as exc:
        raise unprocessable(str(exc)) from exc
    if not req.name.strip():
        raise unprocessable("name: required and must not be empty")
    if not req.source.strip():
        raise unprocessable("source: required and must not be empty")
    if req.source not in SOURCES:
        raise unprocessable(f"source: unknown source {req.source!r}")
    if not req.title.strip():
        raise unprocessable("title: required and must not be empty")
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
    payload = {**body, "id": trigger_id, "created_at": created_at}
    payload["updated_at"] = now.isoformat()
    try:
        return Trigger.from_dict(payload)
    except ValueError as exc:
        raise unprocessable(str(exc)) from exc


def _pick_id(body: Any) -> str:
    """Client-given id when present and non-blank, else a fresh id."""
    if isinstance(body, dict) and isinstance(body.get("id"), str) and body["id"].strip():
        return str(body["id"])
    return new_id()


def _create(fleet_home: Path, body: Any, now: datetime) -> dict[str, Any]:
    """Validate, save with a fresh id, and return the view (runs in a thread)."""
    store = TriggerStore(fleet_home)
    moment = now.isoformat()
    trigger = _validated(fleet_home, body, trigger_id=_pick_id(body), created_at=moment, now=now)
    store.save(trigger)
    return _trigger_view(trigger, store)


def _list(fleet_home: Path) -> dict[str, Any]:
    """All triggers with firing counts (runs in a thread)."""
    store = TriggerStore(fleet_home)
    return {"triggers": [_trigger_view(item, store) for item in store.list()]}


def _sources() -> dict[str, Any]:
    """Every source kind with its param help text (no I/O)."""
    return {"sources": [{"kind": kind, "params": source_params(kind)} for kind in sorted(SOURCES)]}


def _detail(fleet_home: Path, trigger_id: str) -> dict[str, Any] | None:
    """One trigger with its recent firings (runs in a thread)."""
    store = TriggerStore(fleet_home)
    trigger = store.get(trigger_id)
    if trigger is None:
        return None
    return {
        "trigger": _trigger_view(trigger, store),
        "firings": [item.to_dict() for item in store.firings(trigger_id, limit=_DETAIL_LIMIT)],
    }


def _update(fleet_home: Path, trigger_id: str, body: Any, now: datetime) -> dict | None:
    """Validate and rewrite a trigger, keeping id/created_at (runs in a thread)."""
    store = TriggerStore(fleet_home)
    existing = store.get(trigger_id)
    if existing is None:
        return None
    trigger = _validated(
        fleet_home, body, trigger_id=trigger_id, created_at=existing.created_at, now=now
    )
    store.save(trigger)
    return _trigger_view(trigger, store)


def _delete(fleet_home: Path, trigger_id: str) -> bool:
    """Remove a trigger and its firing history (runs in a thread)."""
    return TriggerStore(fleet_home).delete(trigger_id)


def _set_enabled(fleet_home: Path, trigger_id: str, enabled: bool, now: datetime) -> bool:
    """Flip a trigger's enabled flag, bumping updated_at (runs in a thread)."""
    store = TriggerStore(fleet_home)
    existing = store.get(trigger_id)
    if existing is None:
        return False
    store.save(replace(existing, enabled=enabled, updated_at=now.isoformat()))
    return True


def _parse_moment(raw: str) -> datetime | None:
    """Parse a stored ISO-8601 timestamp, or None when unparseable."""
    try:
        moment = datetime.fromisoformat(raw)
    except (TypeError, ValueError):
        return None
    if moment.tzinfo is None:
        return moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC)


def _preview(fleet_home: Path, queue: Any, trigger_id: str, now: datetime) -> dict:
    """Poll the source now and decide per event, opening nothing (in a thread)."""
    store = TriggerStore(fleet_home)
    trigger = store.get(trigger_id)
    if trigger is None:
        raise not_found("trigger", trigger_id)
    try:
        source = source_for(trigger.source)
    except UnknownSource as exc:
        raise unprocessable(f"source: unknown source {trigger.source!r}") from exc
    events = source.poll(
        SourceContext(
            fleet_home=fleet_home, queue=queue, now=now, params=dict(trigger.source_params)
        )
    )
    count = firing_mod.open_count(trigger, queue)
    last = store.last_firing(trigger.id)
    last_at = _parse_moment(last.fired_at) if last is not None else None
    payloads: list[dict[str, str]] = []
    decisions: list[str] = []
    for event in events:
        decision = firing_mod.decide(
            trigger,
            event,
            already_fired=store.has_fired(trigger.id, event.key),
            open_count=count,
            last_fired_at=last_at,
            now=now,
        )
        payloads.append(dict(event.payload))
        decisions.append("open" if decision.action == "open" else decision.reason)
    return {"events": payloads, "decisions": decisions}


@router.get("/triggers", response_model=TriggerListResponse)
async def list_triggers(state: StateDep) -> JSONResponse:
    """Every trigger with firing counts."""
    payload = await asyncio.to_thread(_list, state.fleet_home)
    return JSONResponse(payload)


@router.get("/triggers/sources", response_model=SourceListResponse)
async def list_sources() -> JSONResponse:
    """Every event-source kind with its param help text."""
    return JSONResponse(_sources())


@router.post("/triggers", response_model=TriggerView)
async def create_trigger(request: Request, state: StateDep) -> JSONResponse:
    """Validate and save a trigger; 201 with the view."""
    body = await parse_json_body(request)
    payload = await asyncio.to_thread(_create, state.fleet_home, body, datetime.now(UTC))
    return JSONResponse(payload, status_code=201)


@router.get("/triggers/{trigger_id}", response_model=TriggerDetail)
async def get_trigger(trigger_id: str, state: StateDep) -> JSONResponse:
    """One trigger with its recent firing history."""
    payload = await asyncio.to_thread(_detail, state.fleet_home, trigger_id)
    if payload is None:
        raise not_found("trigger", trigger_id)
    return JSONResponse(payload)


@router.put("/triggers/{trigger_id}", response_model=TriggerView)
async def update_trigger(trigger_id: str, request: Request, state: StateDep) -> JSONResponse:
    """Validate and rewrite a trigger, keeping id and created_at."""
    body = await parse_json_body(request)
    payload = await asyncio.to_thread(
        _update, state.fleet_home, trigger_id, body, datetime.now(UTC)
    )
    if payload is None:
        raise not_found("trigger", trigger_id)
    return JSONResponse(payload)


@router.delete("/triggers/{trigger_id}", response_model=OkResponse)
async def delete_trigger(trigger_id: str, state: StateDep) -> JSONResponse:
    """Remove a trigger and its firing history."""
    removed = await asyncio.to_thread(_delete, state.fleet_home, trigger_id)
    if not removed:
        raise not_found("trigger", trigger_id)
    return JSONResponse({"ok": True})


@router.post("/triggers/{trigger_id}/enable", response_model=OkResponse)
async def enable_trigger(trigger_id: str, state: StateDep) -> JSONResponse:
    """Enable a trigger without resending the full body."""
    enabled = await asyncio.to_thread(
        _set_enabled, state.fleet_home, trigger_id, True, datetime.now(UTC)
    )
    if not enabled:
        raise not_found("trigger", trigger_id)
    return JSONResponse({"ok": True})


@router.post("/triggers/{trigger_id}/disable", response_model=OkResponse)
async def disable_trigger(trigger_id: str, state: StateDep) -> JSONResponse:
    """Disable a trigger without resending the full body."""
    disabled = await asyncio.to_thread(
        _set_enabled, state.fleet_home, trigger_id, False, datetime.now(UTC)
    )
    if not disabled:
        raise not_found("trigger", trigger_id)
    return JSONResponse({"ok": True})


@router.post("/triggers/{trigger_id}/preview", response_model=TriggerPreviewResponse)
async def preview_trigger(trigger_id: str, state: StateDep) -> JSONResponse:
    """Dry run: poll the source now, decide per event, open nothing."""
    payload = await asyncio.to_thread(
        _preview, state.fleet_home, state.queue, trigger_id, datetime.now(UTC)
    )
    return JSONResponse(payload)
