"""FastAPI application factory for `fleet serve` (FR-48, FR-49)."""
from __future__ import annotations

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncGenerator

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

import fleet.ask_human_db as _ahdb
import fleet.telegram as tg
from fleet.ask_human_db import ASK_HUMAN_DB  # re-exported; tests monkeypatch this
from fleet.config import load as load_config
from fleet.daemon import code_fingerprint
from fleet.queue import BeadsQueue, Queue
from fleet.serve.routes.analytics import create_analytics_router
from fleet.serve.routes.beads import create_beads_router
from fleet.serve.routes.chat import create_chat_router
from fleet.serve.routes.config_routes import create_config_router
from fleet.serve.routes.search import create_search_router
from fleet.serve.routes.supervisor import create_supervisor_router
from fleet.serve.routes.tasks import create_tasks_router
from fleet.serve.stats import fleet_home
from fleet.serve.watcher import ConnectionManager, FileWatcher

logger = logging.getLogger(__name__)


def _db_max_created_at() -> float:
    return _ahdb.max_created_at(db_path=ASK_HUMAN_DB)


def _db_fetch_new_questions(since: float) -> list[dict]:
    return _ahdb.fetch_new_questions(since, db_path=ASK_HUMAN_DB)


async def _question_poller(app: FastAPI) -> None:
    watermark: float = await asyncio.to_thread(_db_max_created_at)
    while True:
        try:
            await asyncio.sleep(2.0)
            token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
            cfg = app.state.fleet_state.config
            chat_id = cfg.telegram_chat_id
            if not token or not chat_id:
                continue
            questions = await asyncio.to_thread(_db_fetch_new_questions, watermark)
            new_wm = watermark
            for q in questions:
                agent_id = q.get("agent_id") or "unknown"
                prompt = q.get("prompt") or ""
                options = q.get("options")
                msg = f"[{agent_id}] {prompt}"
                if options:
                    opts = options if isinstance(options, list) else [str(options)]
                    msg += "\n" + "\n".join(f"  {i + 1}. {o}" for i, o in enumerate(opts))
                await tg.send_message(token, chat_id, msg)
                created_at = float(q.get("created_at") or 0)
                if created_at > new_wm:
                    new_wm = created_at
            watermark = new_wm
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("question_poller error")


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
    home = fleet_home()
    resolved_queue = queue if queue is not None else BeadsQueue(home)

    @asynccontextmanager
    async def _lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        home = fleet_home()
        runtime_toml = home / "runtime.toml"
        cfg = load_config(runtime_toml)
        mtime: float | None = runtime_toml.stat().st_mtime if runtime_toml.exists() else None
        app.state.fleet_state = AppState(fleet_home=home, config=cfg, config_mtime=mtime)
        watcher_task = asyncio.create_task(watcher.start(home, mgr))
        poller_task = asyncio.create_task(_question_poller(app))
        listener_task = asyncio.create_task(
            tg.inbound_listener(app, home / "telegram_update_offset")
        )
        try:
            yield
        finally:
            watcher_task.cancel()
            poller_task.cancel()
            listener_task.cancel()
            try:
                await watcher_task
            except asyncio.CancelledError:
                pass
            try:
                await poller_task
            except asyncio.CancelledError:
                pass
            try:
                await listener_task
            except asyncio.CancelledError:
                pass

    app = FastAPI(lifespan=_lifespan)
    app.state.connection_manager = mgr
    app.state.queue = resolved_queue
    app.include_router(create_tasks_router())
    app.include_router(create_beads_router())
    app.include_router(create_supervisor_router())
    app.include_router(create_config_router())
    app.include_router(create_analytics_router())
    app.include_router(create_search_router())
    app.include_router(create_chat_router())

    @app.get("/healthz")
    async def healthz() -> JSONResponse:
        home = fleet_home()
        stored_fp: str | None = None
        serve_pid_file = home / ".serve.pid"
        if serve_pid_file.exists():
            try:
                data = json.loads(serve_pid_file.read_text(encoding="utf-8"))
                stored_fp = data.get("version_fingerprint") if isinstance(data, dict) else None
            except (OSError, json.JSONDecodeError, ValueError):
                pass
        current_fp = code_fingerprint()
        stale = stored_fp is not None and stored_fp != current_fp
        return JSONResponse({
            "status": "ok",
            "fleet_home": str(home),
            "version_fingerprint": stored_fp,
            "current_fingerprint": current_fp,
            "stale": stale,
        })

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

    ui_dist = fleet_home() / "ui_dist"
    if ui_dist.exists():
        app.mount("/", _SPAStaticFiles(directory=ui_dist, html=True), name="static")
    else:
        logger.warning("UI not built — run `cd src/fleet/ui && npm run build` first")

    return app
