"""FastAPI application factory for `fleet serve` (FR-48, FR-49)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from contextlib import asynccontextmanager
from http import HTTPStatus
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import Scope

import fleet.integrations.telegram.notify as tg_notify
from fleet.beads.queue import Queue
from fleet.core.limits import QUESTION_BACKOFF_MAX_SEC, QUESTION_POLL_SEC
from fleet.integrations.telegram.api import TelegramApi
from fleet.integrations.telegram.commands import CommandEnv, parse_allowed_ids
from fleet.integrations.telegram.listener import inbound_listener
from fleet.integrations.telegram.messages import MessageStore, OffsetStore
from fleet.serve.api import ROUTERS
from fleet.serve.errors import register_error_handlers
from fleet.serve.state import AppState, build_state, refresh_config
from fleet.state.paths import fleet_home

logger = logging.getLogger(__name__)

_QUESTION_MSGS = "telegram_question_msgs.json"
_QUESTION_WATERMARK = "telegram_question_watermark"


def _question_messages(state: AppState) -> MessageStore:
    """Reply-routing store for telegram question notifications."""
    return MessageStore(state.fleet_home / _QUESTION_MSGS)


def supervise(coro: Coroutine[Any, Any, None], name: str) -> asyncio.Task[None]:
    """Start *coro* as a background task that logs its own crash.

    A failed serve background task used to surface only at shutdown (or
    never); the done-callback logs the exception with the task name so a
    watcher/poller/listener crash is visible while the server keeps running.
    """
    task = asyncio.create_task(coro)

    def _done(done_task: asyncio.Task[None]) -> None:
        if done_task.cancelled():
            return
        exc = done_task.exception()
        if exc is not None:
            logger.error("background task failed", exc_info=exc, extra={"task": name})

    task.add_done_callback(_done)
    return task


def _load_watermark(path: Path, default: float) -> float:
    """Persisted question watermark, or *default* when absent/invalid."""
    try:
        return max(default, float(path.read_text(encoding="utf-8").strip()))
    except (OSError, ValueError):
        return default


def _save_watermark(path: Path, watermark: float) -> None:
    """Persist the question watermark; a bad disk never kills the poller."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(watermark), encoding="utf-8")
    except OSError as exc:
        logger.warning("question_poller watermark save failed", extra={"error": str(exc)})


async def _question_poller(app: FastAPI) -> None:
    """Forward new ask_human questions to Telegram until cancelled."""
    state = app.state.fleet_state
    token = state.telegram_token
    api = TelegramApi(token)
    watermark_path = state.fleet_home / _QUESTION_WATERMARK
    db_watermark: float = await asyncio.to_thread(state.question_store.max_created_at)
    watermark = await asyncio.to_thread(_load_watermark, watermark_path, db_watermark)
    saved = watermark
    delay = QUESTION_POLL_SEC
    while True:
        try:
            await asyncio.sleep(delay)
            chat_id = state.config.telegram_chat_id if state.config else ""
            if not token or not chat_id:
                delay = QUESTION_POLL_SEC
                continue
            watermark = await tg_notify.notify_new_questions(
                api,
                state.question_store,
                _question_messages(state),
                chat_id,
                watermark,
            )
            if watermark != saved:
                await asyncio.to_thread(_save_watermark, watermark_path, watermark)
                saved = watermark
            delay = QUESTION_POLL_SEC
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("question_poller error")
            delay = min(delay * 2, QUESTION_BACKOFF_MAX_SEC)


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

    def __init__(self, directory: Path) -> None:
        """Mount even when the UI is not built yet; each request re-checks."""
        super().__init__(directory=directory, html=True, check_dir=False)
        self._ui_dir = Path(directory)

    async def get_response(self, path: str, scope: Scope) -> Response:
        if not self._ui_dir.exists():
            return JSONResponse(
                {"error": "UI not built — run just ui-build first"}, status_code=404
            )
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code == HTTPStatus.NOT_FOUND:
                return await super().get_response("index.html", scope)
            raise


def _cors_origins(state: AppState) -> list[str]:
    """Allowed CORS origins from config; [] means same-origin only."""
    if state.config is None:
        return []
    return list(state.config.serve_cors_origins)


def create_app(queue: Queue | None = None) -> FastAPI:
    """Create and configure the fleet FastAPI application."""
    state = build_state(queue)
    mgr = state.connection_manager

    @asynccontextmanager
    async def _lifespan(app: FastAPI):
        refresh_config(state)
        tasks = [
            supervise(state.watcher.start(state.fleet_home), "watcher"),
            supervise(_question_poller(app), "question_poller"),
            supervise(
                inbound_listener(
                    TelegramApi(state.telegram_token),
                    state.question_store,
                    _command_env(state),
                    OffsetStore(state.fleet_home / "telegram_update_offset"),
                ),
                "inbound_listener",
            ),
        ]
        try:
            yield
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    app = FastAPI(lifespan=_lifespan)
    refresh_config(state)
    register_error_handlers(app)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins(state),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["Authorization", "X-Fleet-Token", "Content-Type"],
    )

    app.state.fleet_state = state
    app.state.connection_manager = mgr
    for router in ROUTERS:
        app.include_router(router)

    ui_dist = fleet_home() / "ui_dist"
    if not ui_dist.exists():
        logger.warning("UI not built — run `cd src/fleet/ui && npm run build` first")
    app.mount("/", _SPAStaticFiles(directory=ui_dist), name="static")

    return app
