"""Shared test doubles: one fake per seam, no monkeypatch storms.

Called by any test that needs a scripted telegram API, process runner,
clock, queue, or question store. Each fake records what the code under
test did and plays back scripted responses, so tests inject the fake
through the constructor instead of patching module attributes.

One-stop imports (canonical homes in parentheses):
``FakeClock`` (``fleet.core.clock``), ``FakeQueue`` (``tests/conftest.py``),
``FakeProcess``/``FakeProcessRunner`` (``tests/workers/fake_runner.py``).
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

from fleet.core.clock import FakeClock
from fleet.integrations.ask_human.store import QuestionStore
from fleet.integrations.telegram.api import MAX_TEXT, TelegramApi
from tests.conftest import FakeQueue
from tests.workers.fake_runner import FakeProcess, FakeProcessRunner

__all__ = [
    "FakeClock",
    "FakeProcess",
    "FakeProcessRunner",
    "FakeQueue",
    "FakeQuestionStore",
    "FakeTelegramApi",
    "FakeTelegramServer",
    "make_question_store",
]


class FakeTelegramApi(TelegramApi):
    """Scripted TelegramApi: records calls, plays back queued responses.

    Inject it wherever production code takes a ``TelegramApi`` (the
    listener, the question poller, command dispatch) instead of patching
    ``urlopen`` or ``TelegramApi.send``.
    """

    def __init__(
        self,
        token: str = "tok",
        *,
        updates: list[list[dict]] | None = None,
        message_ids: list[int | None] | None = None,
        fail_with: BaseException | None = None,
    ) -> None:
        super().__init__(token)
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.sent: list[tuple[str, str]] = []
        self.updates_pages = list(updates or [])
        self._message_ids = list(message_ids or [])
        self.fail_with = fail_with

    def call(self, method: str, *, http_timeout: float = 10, **params: Any) -> Any:
        """Record the call; raise the scripted error or return canned data."""
        _ = http_timeout
        self.calls.append((method, dict(params)))
        if self.fail_with is not None:
            raise self.fail_with
        if method == "sendMessage":
            return {"message_id": self._next_id()}
        if method == "getUpdates":
            if self.updates_pages:
                return self.updates_pages.pop(0)
            return []
        if method == "getMe":
            return {"ok": True, "username": "fakebot"}
        raise ValueError(f"unstubbed telegram method {method!r}")

    def fetch_updates(self, offset: int | None) -> list[dict]:
        """Play back the next scripted updates page (records the offset)."""
        _ = offset
        self.calls.append(("getUpdates", {"offset": offset}))
        if self.fail_with is not None:
            raise self.fail_with
        if self.updates_pages:
            return self.updates_pages.pop(0)
        return []

    async def send(self, chat_id: str, text: str) -> None:
        """Record the reply; never raises, like the real client."""
        self.sent.append((chat_id, text[:MAX_TEXT]))

    async def send_with_id(self, chat_id: str, text: str) -> int | None:
        """Record the question send; return the next scripted message id."""
        self.sent.append((chat_id, text[:MAX_TEXT]))
        return self._next_id()

    def _next_id(self) -> int | None:
        """Pop the next scripted message id (defaults to 1)."""
        if self._message_ids:
            return self._message_ids.pop(0)
        return 1


class FakeTelegramServer:
    """Local HTTP stand-in for api.telegram.org for real-client tests.

    Use it when the test target IS ``TelegramApi`` itself (URL shape,
    payload, truncation, error mapping): point the real client at
    ``server.url`` via ``base_url`` instead of patching ``urlopen``.
    """

    def __init__(self, bodies: list[dict] | None = None, status: int = 200) -> None:
        self.bodies = list(bodies or [])
        self.status = status
        self.requests: list[tuple[str, dict]] = []
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        """Base URL to pass as ``TelegramApi(token, base_url)``."""
        assert self._server is not None, "use FakeTelegramServer as a context manager"
        host, port = self._server.server_address
        return f"http://{host}:{port}"

    def __enter__(self) -> FakeTelegramServer:
        """Start the local HTTP server on an ephemeral port."""

        class _Handler(BaseHTTPRequestHandler):
            def _serve(inner: BaseHTTPRequestHandler, raw: bytes) -> None:
                try:
                    body: dict = json.loads(raw.decode()) if raw else {}
                except json.JSONDecodeError:
                    body = {}
                state = inner.server.state  # type: ignore[attr-defined]
                state["requests"].append((f"{inner.command} {inner.path}", body))
                bodies = state["bodies"]
                payload = bodies.pop(0) if bodies else {"ok": True, "result": True}
                data = json.dumps(payload).encode()
                inner.send_response(state["status"])
                inner.send_header("Content-Type", "application/json")
                inner.send_header("Content-Length", str(len(data)))
                inner.end_headers()
                inner.wfile.write(data)

            def do_GET(self) -> None:
                self._serve(b"")

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", 0))
                self._serve(self.rfile.read(length))

            def log_message(self, *args: object) -> None:
                pass

        self._server = HTTPServer(("127.0.0.1", 0), _Handler)
        self._server.state = {  # type: ignore[attr-defined]
            "requests": self.requests,
            "bodies": self.bodies,
            "status": self.status,
        }
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *args: object) -> None:
        """Stop the local HTTP server."""
        assert self._server is not None
        self._server.shutdown()
        self._server.server_close()
        self._server = None


def make_question_store(tmp_path: Path) -> QuestionStore:
    """A real QuestionStore on a throwaway sqlite file (no global db path)."""
    return QuestionStore(tmp_path / "questions.db")


class FakeQuestionStore(QuestionStore):
    """QuestionStore rooted at *tmp_path* (per-test db, nothing shared)."""

    def __init__(self, tmp_path: Path) -> None:
        super().__init__(tmp_path / "questions.db")
