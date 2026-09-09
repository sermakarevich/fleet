"""System routes: health and event websockets (FR-48, FR-49)."""

from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from fleet.observability.daemon import code_fingerprint
from fleet.observability.process import service_status
from fleet.serve.api.models import HealthResponse
from fleet.serve.auth import websocket_authorized
from fleet.serve.state import StateDep
from fleet.state import paths as state_paths

router = APIRouter()


@router.get("/healthz", response_model=HealthResponse)
async def healthz() -> JSONResponse:
    """Liveness with fleet home, serve fingerprint and code staleness."""
    fleet_home = state_paths.fleet_home()
    svc = service_status("serve", fleet_home)
    return JSONResponse(
        {
            "status": "ok",
            "fleet_home": str(fleet_home),
            "version_fingerprint": svc.fingerprint,
            "current_fingerprint": code_fingerprint(),
            "stale": svc.stale,
        }
    )


@router.websocket("/ws/events")
async def ws_events(websocket: WebSocket, state: StateDep) -> None:
    """Global event stream for all tasks."""
    if not websocket_authorized(websocket):
        await websocket.close(code=4401)
        return
    mgr = state.connection_manager
    await mgr.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        await mgr.disconnect(websocket)


@router.websocket("/ws/tasks/{task_id}/events")
async def ws_task_events(websocket: WebSocket, task_id: str, state: StateDep) -> None:
    """Event stream for one task; 4004 when the task does not exist."""
    if not websocket_authorized(websocket):
        await websocket.close(code=4401)
        return
    task_dir = state_paths.task_dir(state_paths.fleet_home(), task_id)
    if not task_dir.is_dir():
        await websocket.accept()
        await websocket.close(code=4004)
        return
    mgr = state.connection_manager
    await mgr.connect(websocket, task_id=task_id)
    try:
        while True:
            await websocket.receive_text()
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        await mgr.disconnect(websocket)
