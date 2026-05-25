"""FastAPI application factory for `fleet serve` (FR-48, FR-49)."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncGenerator

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from fleet.config import load as load_config
from fleet.serve.mcp import PendingQuestionStore, create_mcp_router, create_qa_router
from fleet.serve.stats import fleet_home
from fleet.serve.watcher import ConnectionManager, FileWatcher


@dataclass
class AppState:
    fleet_home: Path
    config: Any
    config_mtime: float | None


def create_app() -> FastAPI:
    """Create and configure the fleet FastAPI application."""
    mgr = ConnectionManager()
    watcher = FileWatcher()
    store = PendingQuestionStore()

    @asynccontextmanager
    async def _lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        home = fleet_home()
        runtime_toml = home / "runtime.toml"
        cfg = load_config(runtime_toml)
        mtime: float | None = runtime_toml.stat().st_mtime if runtime_toml.exists() else None
        app.state.fleet_state = AppState(fleet_home=home, config=cfg, config_mtime=mtime)
        watcher_task = asyncio.create_task(watcher.start(home, mgr))
        try:
            yield
        finally:
            watcher_task.cancel()
            try:
                await watcher_task
            except asyncio.CancelledError:
                pass

    app = FastAPI(lifespan=_lifespan)
    app.state.pending_questions = store
    app.state.connection_manager = mgr
    app.include_router(create_mcp_router(store, mgr))
    app.include_router(create_qa_router(store))

    @app.get("/healthz")
    async def healthz() -> JSONResponse:
        return JSONResponse({"status": "ok", "fleet_home": str(fleet_home())})

    @app.websocket("/ws/events")
    async def ws_events(ws: WebSocket) -> None:
        await mgr.connect(ws)
        try:
            while True:
                await ws.receive_text()
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            await mgr.disconnect(ws)

    @app.websocket("/ws/tasks/{id}/events")
    async def ws_task_events(ws: WebSocket, id: str) -> None:
        task_dir = fleet_home() / "tasks" / id
        if not task_dir.is_dir():
            await ws.accept()
            await ws.close(code=4004)
            return
        await mgr.connect(ws, task_id=id)
        try:
            while True:
                await ws.receive_text()
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            await mgr.disconnect(ws)

    return app
