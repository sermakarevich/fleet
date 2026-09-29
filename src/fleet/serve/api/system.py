"""System routes: health and event websockets (FR-48, FR-49)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from fleet.observability.daemon import code_fingerprint
from fleet.observability.process import service_status
from fleet.serve.api.models import HealthResponse
from fleet.serve.auth import HTTP_AUTH, require_ws_token
from fleet.serve.state import AppState, StateDep
from fleet.state import paths as state_paths

router = APIRouter(dependencies=[HTTP_AUTH])

ws_router = APIRouter()


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


async def _ws_loop(websocket: WebSocket, state: AppState) -> None:
    """Accept the socket and relay until disconnect."""
    mgr = state.connection_manager
    await mgr.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        await mgr.disconnect(websocket)


@ws_router.websocket("/ws/events")
async def ws_events(
    websocket: WebSocket,
    state: StateDep,
    allowed: bool = Depends(require_ws_token),
) -> None:
    """Global event stream for all tasks."""
    if not allowed:
        return
    await _ws_loop(websocket, state)
