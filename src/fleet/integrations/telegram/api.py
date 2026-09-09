"""Telegram Bot HTTP API client, sync and async (setup, notify, commands, listener).

Every Bot API call goes through ``TelegramApi.call`` — the one place that
formats the ``bot<token>/<method>`` URL — so tests point ``base_url`` at a
local fake server instead of monkeypatching ``urlopen``. Module-level
helpers (``get_me``, ``get_updates``, ``send_message_raise``) are thin
wrappers kept for the setup wizard; the poll loop and command handlers use
``TelegramApi`` directly.
"""

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

#: Default Bot API origin; override per-client for tests.
TELEGRAM_API_BASE = "https://api.telegram.org"

MAX_TEXT = 4096

# Bot API method -> HTTP verb. A dispatch table, not an if-chain: unknown
# methods fail fast in TelegramApi.call instead of building a bad request.
_METHOD_HTTP: dict[str, str] = {
    "getMe": "GET",
    "getUpdates": "GET",
    "sendMessage": "POST",
}


def _call(req: urllib.request.Request, timeout: float) -> Any:
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


@dataclass
class TelegramApi:
    """Token-bound client used by the poll loop and command handlers.

    ``base_url`` defaults to the real Bot API; tests pass a local fake
    server URL so no test ever touches the network or patches urlopen.
    """

    token: str
    base_url: str = TELEGRAM_API_BASE

    def call(self, method: str, *, http_timeout: float = 10, **params: Any) -> Any:
        """One Bot API call; return the envelope result, raise on failure.

        ``method`` is a Bot API method name (see ``_METHOD_HTTP``);
        ``params`` become the GET query string or the POST JSON body.
        ``http_timeout`` is the socket timeout, separate from any
        ``timeout`` long-poll param inside ``params``.
        """
        try:
            http_method = _METHOD_HTTP[method]
        except KeyError:
            raise ValueError(f"unknown telegram method {method!r}") from None
        url = f"{self.base_url}/bot{self.token}/{method}"
        if http_method == "GET":
            query = urllib.parse.urlencode(params)
            req = urllib.request.Request(f"{url}?{query}" if query else url, method="GET")
        else:
            payload = json.dumps(params).encode()
            req = urllib.request.Request(
                url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
        return _call(req, http_timeout)

    def fetch_updates(self, offset: int | None) -> list[dict]:
        """Blocking getUpdates with the listener long-poll timeout."""
        return get_updates(self.token, offset=offset, timeout=30, base_url=self.base_url)

    async def send(self, chat_id: str, text: str) -> None:
        """Send a reply; never raises."""
        await asyncio.to_thread(_post_send, self.token, chat_id, text, self.base_url)

    async def send_with_id(self, chat_id: str, text: str) -> int | None:
        """Send a question; return message_id for reply routing."""
        data = await asyncio.to_thread(_post_send, self.token, chat_id, text, self.base_url)
        if not isinstance(data, dict):
            return None
        try:
            mid = data.get("message_id")
            return int(mid) if mid is not None else None
        except (TypeError, ValueError):
            return None


def get_me(token: str, base_url: str = TELEGRAM_API_BASE) -> dict:
    """Call getMe synchronously; return the bot info dict."""
    return TelegramApi(token, base_url).call("getMe")


def get_updates(
    token: str,
    offset: int | None = None,
    timeout: int = 5,
    base_url: str = TELEGRAM_API_BASE,
) -> list[dict]:
    """Blocking getUpdates call; raises on network/API error."""
    params: dict[str, Any] = {"timeout": timeout, "allowed_updates": ["message"]}
    if offset is not None:
        params["offset"] = offset
    return TelegramApi(token, base_url).call("getUpdates", http_timeout=timeout + 10, **params)


def send_message_raise(
    token: str, chat_id: str, text: str, base_url: str = TELEGRAM_API_BASE
) -> None:
    """Send synchronously; raise RuntimeError with the API description."""
    TelegramApi(token, base_url).call("sendMessage", chat_id=chat_id, text=text[:MAX_TEXT])


def _post_send(
    token: str, chat_id: str, text: str, base_url: str = TELEGRAM_API_BASE
) -> Any | None:
    """Sync sendMessage; None (logged) on any failure, never raises."""
    try:
        return TelegramApi(token, base_url).call(
            "sendMessage", chat_id=chat_id, text=text[:MAX_TEXT]
        )
    except Exception as exc:
        _log.error("telegram.send failed", error=str(exc))
        return None
