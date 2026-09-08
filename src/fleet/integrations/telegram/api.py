"""Telegram Bot HTTP API, sync and async (setup, notify, commands, listener)."""

from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

import structlog

_log = structlog.get_logger(__name__)
MAX_TEXT = 4096


def _call(req: urllib.request.Request, timeout: int) -> Any:
    """Perform *req*; return the envelope result, mapping failures to RuntimeError."""
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            data = json.loads(exc.read().decode("utf-8"))
        except (json.JSONDecodeError, AttributeError):
            raise RuntimeError(str(exc)) from exc
        raise RuntimeError(data.get("description", str(exc))) from exc
    if isinstance(data, dict) and not data.get("ok"):
        raise RuntimeError(data.get("description", "telegram call failed"))
    return data.get("result") if isinstance(data, dict) else data


def get_me(token: str) -> dict:
    """Call getMe synchronously; return the bot info dict."""
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/getMe", method="GET")
    return _call(req, 10)


def get_updates(token: str, offset: int | None = None, timeout: int = 5) -> list[dict]:
    """Blocking getUpdates call; raises on network/API error."""
    base: dict[str, Any] = {"timeout": timeout, "allowed_updates": ["message"]}
    params = base | ({"offset": offset} if offset is not None else {})
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/getUpdates?{urllib.parse.urlencode(params)}",
        method="GET",
    )
    return _call(req, timeout + 10)


def _post(token: str, chat_id: str, text: str) -> urllib.request.Request:
    """Build a sendMessage POST (text truncated to MAX_TEXT)."""
    payload = json.dumps({"chat_id": chat_id, "text": text[:MAX_TEXT]}).encode()
    return urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )


def send_message_raise(token: str, chat_id: str, text: str) -> None:
    """Send synchronously; raise RuntimeError with the API description."""
    _call(_post(token, chat_id, text), 10)


def _post_send(token: str, chat_id: str, text: str) -> Any | None:
    """Sync sendMessage; None (logged) on any failure, never raises."""
    try:
        return _call(_post(token, chat_id, text), 10)
    except Exception as exc:
        _log.error("telegram.send failed", error=str(exc))
        return None


@dataclass
class TelegramApi:
    """Token-bound client used by the poll loop and command handlers."""

    token: str

    def fetch_updates(self, offset: int | None) -> list[dict]:
        """Blocking getUpdates with the listener long-poll timeout."""
        return get_updates(self.token, offset=offset, timeout=30)

    async def send(self, chat_id: str, text: str) -> None:
        """Send a reply; never raises."""
        await asyncio.to_thread(_post_send, self.token, chat_id, text)

    async def send_with_id(self, chat_id: str, text: str) -> int | None:
        """Send a question; return message_id for reply routing."""
        data = await asyncio.to_thread(_post_send, self.token, chat_id, text)
        if not isinstance(data, dict):
            return None
        try:
            mid = data.get("message_id")
            return int(mid) if mid is not None else None
        except (TypeError, ValueError):
            return None
