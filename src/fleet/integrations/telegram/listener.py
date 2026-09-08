"""Inbound Telegram poll loop: fetch, filter allowed senders, dispatch.

Called by serve/app.py with dependencies built from AppState (api token,
question store, command env, offset file); never touches app.state.
Runs until cancelled; network errors back off exponentially.
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog

from .api import TelegramApi
from .commands import CommandEnv
from .messages import OffsetStore

_log = structlog.get_logger(__name__)

_IDLE_POLL_SEC = 10  # sleep while the allowlist is empty (default-deny)
_BACKOFF_MAX = 60  # slowest retry after repeated poll failures


def _fetch_updates(api: TelegramApi, offset: int | None) -> list[dict]:
    """One getUpdates round (own function so tests can stub the poll)."""
    return api.fetch_updates(offset)


async def inbound_listener(
    api: TelegramApi, store: Any, commands: CommandEnv, offset_store: OffsetStore
) -> None:
    """Long-poll getUpdates; create tasks and answer questions until cancelled."""
    if not api.token:
        _log.debug("telegram.inbound_listener: no token, listener inactive")
        return
    offset = offset_store.load()
    backoff = 1.0
    while True:
        try:
            allowed = commands.allowed_ids()
            if not allowed:
                await asyncio.sleep(_IDLE_POLL_SEC)
                continue
            updates = await asyncio.to_thread(_fetch_updates, api, offset)
            backoff = 1.0
            for update in updates:
                offset = update.get("update_id", 0) + 1
                if commands.is_allowed(update, allowed):
                    await commands.dispatch(api, store, update)
                else:
                    _log_rejected(update)
                offset_store.save(offset)
        except asyncio.CancelledError:
            raise
        except Exception:
            _log.exception("telegram.inbound: error, backing off", backoff=backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, _BACKOFF_MAX)


def _log_rejected(update: dict) -> None:
    """Log one update dropped for a sender outside the allowlist."""
    msg = update.get("message") or {}
    _log.warning(
        "telegram.inbound: rejected sender",
        from_id=str((msg.get("from") or {}).get("id", "?")),
        chat_id=str((msg.get("chat") or {}).get("id", "?")),
    )
