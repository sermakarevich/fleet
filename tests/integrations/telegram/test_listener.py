"""Listener tests with a fake api (no HTTP, no app.state).

FakeApi implements TelegramApi's three methods over canned updates; the
store, command env, messages and offsets are real. Each test drives
inbound_listener until the fake raises CancelledError.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from fleet.integrations.ask_human.store import QuestionStore
from fleet.integrations.telegram.api import TelegramApi
from fleet.integrations.telegram.commands import CommandEnv, parse_allowed_ids
from fleet.integrations.telegram.listener import inbound_listener
from fleet.integrations.telegram.messages import MessageStore, OffsetStore
from tests.integrations.telegram.conftest import SleepScript


class FakeApi(TelegramApi):
    """TelegramApi double playing canned updates; records sends and offsets."""

    def __init__(self, updates: list[dict] | None = None, token: str = "tok") -> None:
        super().__init__(token=token)
        self._updates = list(updates) if updates is not None else None
        self.sent: list[tuple[str, str]] = []
        self.seen_offsets: list[int | None] = []

    def fetch_updates(self, offset: int | None) -> list[dict]:
        """First call returns the canned updates, later calls end the test."""
        self.seen_offsets.append(offset)
        if self._updates is not None:
            updates, self._updates = self._updates, None
            return updates
        raise asyncio.CancelledError()

    async def send(self, chat_id: str, text: str) -> None:
        self.sent.append((chat_id, text))

    async def send_with_id(self, chat_id: str, text: str) -> int | None:
        self.sent.append((chat_id, text))
        return 7


def _parts(
    tmp_path: Path,
    api: FakeApi,
    queue: Any = None,
    allowed_ids: str = "123",
    db: bool = True,
) -> tuple[QuestionStore, CommandEnv, OffsetStore]:
    """Real store/env/offsets around the fake api."""
    return (
        QuestionStore(tmp_path / "questions.db") if db else MagicMock(),
        CommandEnv(
            queue=queue or MagicMock(),
            messages=MessageStore(tmp_path / "qmsgs.json"),
            allowed_ids=lambda: parse_allowed_ids(allowed_ids),
            default_cwd=lambda: None,
        ),
        OffsetStore(tmp_path / "offset"),
    )


def _update(text: str, update_id: int = 5, sender: int = 123) -> dict:
    return {
        "update_id": update_id,
        "message": {"from": {"id": sender}, "chat": {"id": sender}, "text": text},
    }


def test_no_token_returns_without_fetching(tmp_path: Path) -> None:
    """Empty token exits immediately; fetch is never called."""
    api = FakeApi(token="")
    store, env, offsets = _parts(tmp_path, api)
    asyncio.run(inbound_listener(api, store, env, offsets))
    assert api.seen_offsets == []


def test_empty_allowlist_never_fetches(tmp_path: Path) -> None:
    """Default-deny: no allowlist means sleep, never getUpdates."""
    api = FakeApi([_update("/help")])
    store, env, offsets = _parts(tmp_path, api, allowed_ids="")

    sleep = SleepScript(stop_after=2)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(inbound_listener(api, store, env, offsets, sleep_fn=sleep))
    assert api.seen_offsets == []


def test_allowed_command_dispatches_and_advances_offset(tmp_path: Path) -> None:
    """/help dispatches to a reply and the offset moves past the update."""
    api = FakeApi([_update("/help", update_id=10)])
    store, env, offsets = _parts(tmp_path, api)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(inbound_listener(api, store, env, offsets))
    assert len(api.sent) == 1
    assert "/new_task" in api.sent[0][1]
    assert offsets.load() == 11
    assert api.seen_offsets[0] is None


def test_rejected_sender_gets_no_reply_but_offset_advances(tmp_path: Path) -> None:
    """Non-allowlisted senders are dropped silently; polling still advances."""
    api = FakeApi([_update("/new_task Evil", update_id=3, sender=111)])
    queue: MagicMock = MagicMock()
    store, env, offsets = _parts(tmp_path, api, queue=queue, allowed_ids="999")
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(inbound_listener(api, store, env, offsets))
    assert api.sent == []
    queue.create_task.assert_not_called()
    assert offsets.load() == 4


def test_saved_offset_is_passed_to_fetch(tmp_path: Path) -> None:
    """A persisted offset resumes polling where the last run stopped."""
    offsets = OffsetStore(tmp_path / "offset")
    offsets.save(8)
    api = FakeApi()
    store, env, _ = _parts(tmp_path, api)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(inbound_listener(api, store, env, offsets))
    assert api.seen_offsets == [8]


def test_network_error_backs_off_and_continues(tmp_path: Path) -> None:
    """A failed poll sleeps with backoff; the loop survives it."""
    api = FakeApi([_update("/help")])
    calls = [0]
    real_fetch = api.fetch_updates

    def _flaky(offset: int | None) -> list[dict]:
        calls[0] += 1
        if calls[0] == 1:
            raise OSError("network boom")
        return real_fetch(offset)

    api.fetch_updates = _flaky  # type: ignore[method-assign]
    store, env, offsets = _parts(tmp_path, api)

    sleep = SleepScript(stop_after=None)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(inbound_listener(api, store, env, offsets, sleep_fn=sleep))
    assert sleep.calls[:1] == [1.0]
    assert len(api.sent) == 1


def test_plain_text_answers_single_pending_question(tmp_path: Path) -> None:
    """End to end: question in the store, plain-text reply answers it."""
    api = FakeApi([_update("blue")])
    store, env, offsets = _parts(tmp_path, api)
    qid = store.create("color?", agent_id="agent-9")
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(inbound_listener(api, store, env, offsets))
    assert len(api.sent) == 1
    assert "agent-9" in api.sent[0][1]
    assert store.get(qid)["status"] == "answered"
