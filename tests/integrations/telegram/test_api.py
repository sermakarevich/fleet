"""TelegramApi against a local fake Bot API server (no network, no patching).

``TelegramApi(token, base_url=...)`` points at a fake server in a
background thread; every assertion below runs against real HTTP, so the
URL shapes, query encoding, and JSON bodies are covered exactly as the
bot sends them.
"""

from __future__ import annotations

import asyncio
import json
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from fleet.integrations.telegram.api import (
    TELEGRAM_API_BASE,
    TelegramApi,
    get_me,
    get_updates,
    send_message_raise,
)

_TOKEN = "faketoken"


class _FakeBot(BaseHTTPRequestHandler):
    """Minimal Bot API double: records requests, answers from canned routes."""

    requests: list[dict] = []

    def log_message(self, *args) -> None:  # silence stderr during tests
        pass

    def _send(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _record(self) -> tuple[str, str, dict]:
        parsed = urllib.parse.urlparse(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        body = json.loads(raw.decode()) if raw else {}
        self.requests.append(
            {"verb": self.command, "path": parsed.path, "query": parsed.query, "body": body}
        )
        return self.command, parsed.path, body

    def do_GET(self) -> None:
        _, path, _ = self._record()
        query = self.requests[-1]["query"]
        if path == f"/bot{_TOKEN}/getMe":
            if "fail=yes" in query:
                self._send_plain(b"boom", status=500)
            else:
                self._send({"ok": True, "result": {"username": "fakebot"}})
        elif path == f"/bot{_TOKEN}/getUpdates":
            self._send({"ok": True, "result": [{"update_id": 3}]})
        else:
            self._send({"ok": False, "description": "Not Found"}, status=404)

    def _send_plain(self, body: bytes, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        _, path, body = self._record()
        if path == f"/bot{_TOKEN}/sendMessage":
            if body.get("text") == "boom":
                self._send({"ok": False, "description": "Bad Request: boom"})
            else:
                self._send({"ok": True, "result": {"message_id": 7, "text": body.get("text")}})
        else:
            self._send({"ok": False, "description": "Not Found"}, status=404)


@pytest.fixture
def api_url() -> str:
    """Base URL of the fake Bot API server (background thread, closed after)."""
    _FakeBot.requests = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeBot)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        thread.join()


def test_default_base_url_is_telegram(api_url: str):
    assert TELEGRAM_API_BASE == "https://api.telegram.org"
    assert api_url.startswith("http://127.0.0.1:")


def test_get_me_returns_bot_info(api_url: str):
    assert get_me(_TOKEN, base_url=api_url) == {"username": "fakebot"}
    assert _FakeBot.requests[-1]["path"] == f"/bot{_TOKEN}/getMe"


def test_get_updates_sends_offset_and_timeout(api_url: str):
    updates = get_updates(_TOKEN, offset=3, timeout=5, base_url=api_url)
    assert updates == [{"update_id": 3}]
    query = urllib.parse.parse_qs(_FakeBot.requests[-1]["query"])
    assert query["offset"] == ["3"]
    assert query["timeout"] == ["5"]


def test_send_posts_json_body(api_url: str):
    api = TelegramApi(_TOKEN, base_url=api_url)
    asyncio.run(api.send("123", "hello"))
    sent = _FakeBot.requests[-1]
    assert sent["path"] == f"/bot{_TOKEN}/sendMessage"
    assert sent["body"] == {"chat_id": "123", "text": "hello"}


def test_send_truncates_long_text(api_url: str):
    api = TelegramApi(_TOKEN, base_url=api_url)
    asyncio.run(api.send("cid", "a" * 5000))
    assert len(_FakeBot.requests[-1]["body"]["text"]) == 4096


def test_send_with_id_returns_message_id(api_url: str):
    api = TelegramApi(_TOKEN, base_url=api_url)
    assert asyncio.run(api.send_with_id("123", "hello")) == 7


def test_api_error_raises_with_description(api_url: str):
    api = TelegramApi(_TOKEN, base_url=api_url)
    with pytest.raises(RuntimeError, match="Bad Request: boom"):
        api.call("sendMessage", chat_id="123", text="boom")


def test_http_error_raises(api_url: str):
    api = TelegramApi(_TOKEN, base_url=api_url)
    with pytest.raises(RuntimeError):
        api.call("getMe", fail="yes")


def test_unknown_method_fails_fast(api_url: str):
    api = TelegramApi(_TOKEN, base_url=api_url)
    with pytest.raises(ValueError, match="unknown telegram method"):
        api.call("deleteEverything")


def test_send_message_raise_sends_and_returns_none(api_url: str):
    assert send_message_raise(_TOKEN, "123", "hi", base_url=api_url) is None
    assert _FakeBot.requests[-1]["body"]["text"] == "hi"
