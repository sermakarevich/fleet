"""FastAPI application factory for `fleet serve` (FR-48, FR-49)."""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, suppress
from http import HTTPStatus

from fastapi import FastAPI
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import Scope

import fleet.integrations.telegram.notify as tg_notify
from fleet.beads.queue import Queue
from fleet.integrations.telegram.api import TelegramApi
from fleet.integrations.telegram.commands import CommandEnv, parse_allowed_ids
from fleet.integrations.telegram.listener import inbound_listener
from fleet.integrations.telegram.messages import MessageStore, OffsetStore
from fleet.serve.api import ROUTERS
from fleet.serve.auth import install_auth
from fleet.serve.state import AppState, build_state, refresh_config
from fleet.state.paths import fleet_home

logger = logging.getLogger(__name__)

_QUESTION_MSGS = "telegram_question_msgs.json"
_QUESTION_POLL_SEC = 2.0


def _question_messages(state: AppState) -> MessageStore:
    """Reply-routing store for telegram question notifications."""
    return MessageStore(state.fleet_home / _QUESTION_MSGS)


async def _question_poller(app: FastAPI) -> None:
    """Forward new ask_human questions to Telegram until cancelled."""
    state = app.state.fleet_state
    watermark: float = await asyncio.to_thread(state.question_store.max_created_at)
    while True:
        try:
            await asyncio.sleep(_QUESTION_POLL_SEC)
            token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
            chat_id = state.config.telegram_chat_id if state.config else ""
            if not token or not chat_id:
                continue
            watermark = await tg_notify.notify_new_questions(
                TelegramApi(token),
                state.question_store,
                _question_messages(state),
                chat_id,
                watermark,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("question_poller error")


def _command_env(state: AppState) -> CommandEnv:
    """Handler dependencies for the inbound listener, read live from state."""
    return CommandEnv(
        queue=state.queue,
        messages=_question_messages(state),
        allowed_ids=lambda: parse_allowed_ids(
            state.config.telegram_allowed_ids if state.config else ""
        ),
        default_cwd=lambda: (state.config.telegram_default_cwd if state.config else "") or None,
    )


class _SPAStaticFiles(StaticFiles):
    """StaticFiles subclass that serves index.html for any unmatched path (SPA fallback)."""

    async def get_response(self, path: str, scope: Scope) -> Response:
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
        watcher_task = asyncio.create_task(state.watcher.start(state.fleet_home))
        poller_task = asyncio.create_task(_question_poller(app))
        listener_task = asyncio.create_task(
            inbound_listener(
                TelegramApi(os.environ.get("TELEGRAM_BOT_TOKEN", "")),
                state.question_store,
                _command_env(state),
                OffsetStore(state.fleet_home / "telegram_update_offset"),
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
    for router in ROUTERS:
        app.include_router(router)

    ui_dist = fleet_home() / "ui_dist"
    if ui_dist.exists():
        app.mount("/", _SPAStaticFiles(directory=ui_dist, html=True), name="static")
    else:
        logger.warning("UI not built — run `cd src/fleet/ui && npm run build` first")

    return app
