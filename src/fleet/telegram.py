from __future__ import annotations

import asyncio
import json
import os
import urllib.request

import structlog

_MAX_TEXT = 4096
_log = structlog.get_logger(__name__)


def is_configured() -> bool:
    """Return True if TELEGRAM_BOT_TOKEN env var is set and non-empty."""
    return bool(os.environ.get("TELEGRAM_BOT_TOKEN"))


async def send_message(token: str, chat_id: str, text: str) -> None:
    """POST text to Telegram sendMessage; fire-and-forget, never raises."""
    text = text[:_MAX_TEXT]
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps({"chat_id": chat_id, "text": text}).encode()

    def _post() -> None:
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()

    try:
        await asyncio.to_thread(_post)
    except Exception as exc:
        _log.error("telegram.send_message failed", error=str(exc))
