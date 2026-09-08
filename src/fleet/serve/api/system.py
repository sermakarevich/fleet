"""System routes: health and event websockets (FR-48, FR-49)."""

from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from fleet.observability.daemon import code_fingerprint
from fleet.observability.process import service_status
from fleet.serve.api.models import HealthResponse
from fleet.serve.auth import websocket_authorized
from fleet.serve.state import StateDep
from fleet.state.paths import fleet_home
from fleet.state.paths import task_dir as _task_dir

router = APIRouter()


@router.get("/healthz", response_model=HealthResponse)
async def healthz() -> JSONResponse:
    """Liveness with fleet home, serve fingerprint and code staleness."""
    home = fleet_home()
    svc = service_status("serve", home)
    return JSONResponse(
        {
            "status": "ok",
            "fleet_home": str(home),
            "version_fingerprint": svc.fingerprint,
            "current_fingerprint": code_fingerprint(),
            "stale": svc.stale,
        }
    )


@router.websocket("/ws/events")
async def ws_events(ws: WebSocket, state: StateDep) -> None:
    """Global event stream for all tasks."""
    if not websocket_authorized(ws):
        await ws.close(code=4401)
        return
    mgr = state.connection_manager
    await mgr.connect(ws)
    try:
        while True:
            await ws.receive_text()
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        await mgr.disconnect(ws)


@router.websocket("/ws/tasks/{id}/events")
async def ws_task_events(ws: WebSocket, id: str, state: StateDep) -> None:
    """Event stream for one task; 4004 when the task does not exist."""
    if not websocket_authorized(ws):
        await ws.close(code=4401)
        return
    task_dir = _task_dir(fleet_home(), id)
    if not task_dir.is_dir():
        await ws.accept()
        await ws.close(code=4004)
        return
    mgr = state.connection_manager
    await mgr.connect(ws, task_id=id)
    try:
        while True:
            await ws.receive_text()
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        await mgr.disconnect(ws)
