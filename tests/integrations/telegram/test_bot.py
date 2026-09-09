"""Tests for the Telegram answer store and send (units under test: messages.py
MessageStore and integrations/telegram/api.py::TelegramApi.send_with_id).

The store tests use a real ``MessageStore`` on ``tmp_path``; the send tests
drive the real client against a local ``FakeTelegramServer``. Answer flows
live in ``test_bot_answer.py``.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fleet.integrations.telegram.api import TelegramApi
from fleet.integrations.telegram.messages import MessageStore
from tests.helpers.fakes import FakeTelegramServer


def test_record_and_lookup_round_trip(tmp_path: Path) -> None:
    """record_question_message then lookup_question_for_message returns the stored qid."""
    messages = MessageStore(tmp_path / "q_msgs.json")
    messages.record(101, "q-abc")
    assert messages.lookup(101) == "q-abc"
    assert messages.lookup(999) is None


def test_200_entry_cap_eviction(tmp_path: Path) -> None:
    """Inserting 205 entries evicts the 5 oldest; exactly 200 remain."""
    path = tmp_path / "q_msgs.json"
    messages = MessageStore(path)
    for i in range(205):
        messages.record(i, f"q-{i}")
    mapping = json.loads(path.read_text())
    assert len(mapping) == 200
    for i in range(5):
        assert str(i) not in mapping, f"entry {i} should have been evicted"
    assert "5" in mapping
    assert "204" in mapping


def test_send_message_with_id_returns_message_id() -> None:
    """Returns the integer message_id parsed from a successful sendMessage response."""
    bodies = [{"ok": True, "result": {"message_id": 77}}]
    with FakeTelegramServer(bodies=bodies) as server:
        result = asyncio.run(TelegramApi("tok", server.url).send_with_id("123", "hello"))
    assert result == 77


def test_send_message_with_id_returns_none_on_http_error() -> None:
    """Returns None when the HTTP call raises an exception."""
    with FakeTelegramServer(status=500, bodies=[{"ok": False, "description": "refused"}]) as server:
        assert asyncio.run(TelegramApi("tok", server.url).send_with_id("123", "hi")) is None


def test_send_message_with_id_returns_none_when_ok_false() -> None:
    """Returns None when Telegram responds with ok=false."""
    with FakeTelegramServer(bodies=[{"ok": False, "description": "Bad Request"}]) as server:
        assert asyncio.run(TelegramApi("tok", server.url).send_with_id("123", "hi")) is None
