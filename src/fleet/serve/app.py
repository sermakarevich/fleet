"""FastAPI application factory for `fleet serve` (FR-48, FR-49)."""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, suppress
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

import fleet.integrations.ask_human.store as _ahdb
import fleet.integrations.telegram.bot as tg
from fleet.beads.queue import Queue
from fleet.integrations.ask_human.store import ASK_HUMAN_DB  # re-exported; tests monkeypatch this
from fleet.serve.api import ROUTERS
from fleet.serve.auth import install_auth
from fleet.serve.state import build_state, refresh_config
from fleet.state.paths import fleet_home

logger = logging.getLogger(__name__)


def _db_max_created_at() -> float:
    return _ahdb.max_created_at(db_path=ASK_HUMAN_DB)


def _db_fetch_new_questions(since: float) -> list[dict]:
    return _ahdb.fetch_new(since, db_path=ASK_HUMAN_DB)


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
            home = app.state.fleet_state.home
            for q in questions:
                agent_id = q.get("agent_id") or "unknown"
                prompt = q.get("prompt") or ""
                options = q.get("options")
                msg = f"[{agent_id}] {prompt}"
                if options:
                    opts = options if isinstance(options, list) else [str(options)]
                    msg += "\n" + "\n".join(f"  {i + 1}. {o}" for i, o in enumerate(opts))
                message_id = await tg.send_message_with_id(token, chat_id, msg)
                if message_id is not None:
                    q_id = q.get("id")
                    if q_id:
                        tg.record_question_message(
                            home / "telegram_question_msgs.json",
                            message_id,
                            q_id,
                        )
                created_at = float(q.get("created_at") or 0)
                new_wm = max(new_wm, created_at)
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
            if exc.status_code == HTTPStatus.NOT_FOUND:
                return await super().get_response("index.html", scope)
            raise


def create_app(queue: Queue | None = None) -> FastAPI:
    """Create and configure the fleet FastAPI application."""
    state = build_state(queue)
    mgr = state.connection_manager

    @asynccontextmanager
    async def _lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        refresh_config(state)
        watcher_task = asyncio.create_task(state.watcher.start(state.home, mgr))
        poller_task = asyncio.create_task(_question_poller(app))
        listener_task = asyncio.create_task(
            tg.inbound_listener(
                app,
                state.home / "telegram_update_offset",
                state.home / "telegram_question_msgs.json",
            )
        )
        try:
            yield
        finally:
            watcher_task.cancel()
            poller_task.cancel()
            listener_task.cancel()
            with suppress(asyncio.CancelledError):
                await watcher_task
            with suppress(asyncio.CancelledError):
                await poller_task
            with suppress(asyncio.CancelledError):
                await listener_task

    app = FastAPI(lifespan=_lifespan)
    refresh_config(state)
    install_auth(app)

    app.state.fleet_state = state
    app.state.connection_manager = mgr
    app.state.queue = state.queue
    for router in ROUTERS:
        app.include_router(router)

    ui_dist = fleet_home() / "ui_dist"
    if ui_dist.exists():
        app.mount("/", _SPAStaticFiles(directory=ui_dist, html=True), name="static")
    else:
        logger.warning("UI not built — run `cd src/fleet/ui && npm run build` first")

    return app
