"""FastAPI application factory for `fleet serve` (FR-48, FR-49)."""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncGenerator

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from fleet.config import load as load_config
from fleet.queue import BeadsQueue, Queue
from fleet.serve.mcp import PendingQuestionStore, create_mcp_router, create_qa_router
from fleet.serve.routes.analytics import create_analytics_router
from fleet.serve.routes.config_routes import create_config_router
from fleet.serve.routes.qa import create_qa_list_router
from fleet.serve.routes.search import create_search_router
from fleet.serve.routes.supervisor import create_supervisor_router
from fleet.serve.routes.tasks import create_tasks_router
from fleet.serve.stats import fleet_home
from fleet.serve.watcher import ConnectionManager, FileWatcher

logger = logging.getLogger(__name__)


class _SPAStaticFiles(StaticFiles):
    """StaticFiles subclass that serves index.html for any unmatched path (SPA fallback)."""

    async def get_response(self, path: str, scope: Any) -> Response:
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code == 404:
                return await super().get_response("index.html", scope)
            raise


@dataclass
class AppState:
    fleet_home: Path
    config: Any
    config_mtime: float | None


def create_app(queue: Queue | None = None) -> FastAPI:
    """Create and configure the fleet FastAPI application."""
    mgr = ConnectionManager()
    watcher = FileWatcher()
    store = PendingQuestionStore()
    resolved_queue = queue if queue is not None else BeadsQueue(fleet_home())

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
    app.state.queue = resolved_queue
    app.include_router(create_mcp_router(store, mgr))
    app.include_router(create_qa_router(store))
    app.include_router(create_tasks_router())
    app.include_router(create_supervisor_router())
    app.include_router(create_config_router())
    app.include_router(create_qa_list_router())
    app.include_router(create_analytics_router())
    app.include_router(create_search_router())

    @app.get("/healthz")
    async def healthz() -> JSONResponse:
        return JSONResponse({"status": "ok", "fleet_home": str(fleet_home())})

    ui_dist = fleet_home() / "ui_dist"
    if ui_dist.exists():
        app.mount("/", _SPAStaticFiles(directory=ui_dist, html=True), name="static")
    else:
        logger.warning("UI not built — run `cd src/fleet/ui && npm run build` first")

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
