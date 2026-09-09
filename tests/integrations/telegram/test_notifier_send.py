"""Tests for the Telegram send paths (unit under test: integrations/telegram/api.py).

The real ``TelegramApi`` client talks to a local ``FakeTelegramServer``
instead of patched ``urlopen`` doubles, so URL shape, payload, truncation,
and error mapping are covered without patching anything.
"""

from __future__ import annotations

import asyncio

from fleet.integrations.telegram.api import TELEGRAM_API_BASE, TelegramApi
from tests.helpers.fakes import FakeTelegramServer


def test_send_message_posts_correct_url_and_payload() -> None:
    """send_message POSTs to the correct Bot API URL with the right JSON payload."""
    with FakeTelegramServer() as server:
        asyncio.run(TelegramApi("mytoken", server.url).send("123", "hello"))

    assert len(server.requests) == 1
    path, body = server.requests[0]
    assert path == "POST /botmytoken/sendMessage"
    assert body == {"chat_id": "123", "text": "hello"}


def test_default_base_url_is_telegram_org() -> None:
    """The default base URL still points at the real Bot API origin."""
    assert TELEGRAM_API_BASE == "https://api.telegram.org"


def test_send_message_truncates_to_4096_chars() -> None:
    """send_message silently truncates text to 4096 characters."""
    with FakeTelegramServer() as server:
        asyncio.run(TelegramApi("tok", server.url).send("cid", "a" * 5000))

    assert len(server.requests) == 1
    assert len(server.requests[0][1]["text"]) == 4096


def test_send_message_swallows_exception_and_does_not_raise() -> None:
    """send_message never raises; HTTP errors are swallowed."""
    with FakeTelegramServer(status=500, bodies=[{"ok": False, "description": "boom"}]) as server:
        asyncio.run(TelegramApi("tok", server.url).send("cid", "hi"))  # must not raise


# (is_configured was dead code in src — removed with its tests per ARCH rule 5.)


def test_send_message_with_id_returns_message_id() -> None:
    """Returns message_id int on a successful Telegram response."""
    bodies = [{"ok": True, "result": {"message_id": 42}}]
    with FakeTelegramServer(bodies=bodies) as server:
        result = asyncio.run(TelegramApi("tok", server.url).send_with_id("123", "hello"))
    assert result == 42


def test_send_message_with_id_returns_none_on_http_error() -> None:
    """Returns None when the HTTP call fails."""
    with FakeTelegramServer(status=500, bodies=[{"ok": False, "description": "refused"}]) as server:
        assert asyncio.run(TelegramApi("tok", server.url).send_with_id("123", "hi")) is None


def test_send_message_with_id_returns_none_when_ok_false() -> None:
    """Returns None when Telegram responds ok=false."""
    with FakeTelegramServer(bodies=[{"ok": False, "description": "Bad Request"}]) as server:
        assert asyncio.run(TelegramApi("tok", server.url).send_with_id("123", "hi")) is None


def test_send_message_with_id_truncates_to_4096() -> None:
    """Text is truncated to 4096 chars before sending."""
    bodies = [{"ok": True, "result": {"message_id": 1}}]
    with FakeTelegramServer(bodies=bodies) as server:
        asyncio.run(TelegramApi("tok", server.url).send_with_id("cid", "x" * 5000))
    assert [len(body["text"]) for _, body in server.requests] == [4096]
