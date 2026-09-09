"""Tests for the serve question poller (unit under test: serve/app.py::_question_poller).

The poll loop gets a ``FakeTelegramApi`` and a ``SleepScript`` through its
injection seams — no patching of ``TelegramApi`` methods or ``asyncio``.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

import fleet.serve.app as app_mod
from fleet.integrations.ask_human.store import QuestionStore
from tests.helpers.fakes import FakeTelegramApi
from tests.integrations.telegram.conftest import (
    SleepScript,
    create_questions_db,
    insert_question,
    make_fake_app,
)


def test_poller_skips_send_when_token_missing(tmp_path: Path) -> None:
    """No send call is made when the token is absent (silent no-op)."""
    db_path = tmp_path / "questions.db"
    create_questions_db(db_path)
    api = FakeTelegramApi("")
    sleep = SleepScript(
        stop_after=2,
        hooks={1: lambda: insert_question(db_path, qid="q1", prompt="x", created_at=500.0)},
    )
    app = make_fake_app(store=QuestionStore(db_path), fleet_home=tmp_path, token="")

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(app_mod._question_poller(app, api=api, sleep_fn=sleep))

    assert api.sent == [], "No messages should be sent when token is absent"


def test_poller_does_not_send_preexisting_rows(tmp_path: Path) -> None:
    """Pre-existing pending rows at startup are NOT sent (watermark baseline)."""
    db_path = tmp_path / "questions.db"
    create_questions_db(db_path)
    insert_question(db_path, qid="q-pre", prompt="old question", created_at=1000.0)
    api = FakeTelegramApi("tok")
    sleep = SleepScript(stop_after=2)
    app = make_fake_app(store=QuestionStore(db_path), fleet_home=tmp_path)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(app_mod._question_poller(app, api=api, sleep_fn=sleep))

    assert api.sent == [], "Pre-existing rows must not be sent"


def test_poller_sends_new_question_exactly_once(tmp_path: Path) -> None:
    """A newly inserted pending row is sent exactly once."""
    db_path = tmp_path / "questions.db"
    create_questions_db(db_path)
    insert_question(db_path, qid="q-pre", prompt="pre-existing", created_at=1000.0)
    api = FakeTelegramApi("tok")
    sleep = SleepScript(
        stop_after=3,
        hooks={
            1: lambda: insert_question(
                db_path, qid="q-new", prompt="new question?", created_at=2000.0
            )
        },
    )
    app = make_fake_app(store=QuestionStore(db_path), fleet_home=tmp_path)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(app_mod._question_poller(app, api=api, sleep_fn=sleep))

    assert len(api.sent) == 1
    assert "new question?" in api.sent[0][1]


def test_poller_continues_after_send_error(tmp_path: Path) -> None:
    """A send error does not kill the poll loop."""
    db_path = tmp_path / "questions.db"
    create_questions_db(db_path)  # empty → watermark = 0.0
    api = FakeTelegramApi("tok", send_failures=[RuntimeError("network boom")])
    sleep = SleepScript(
        stop_after=4,
        hooks={1: lambda: insert_question(db_path, qid="q1", prompt="failing", created_at=500.0)},
    )
    app = make_fake_app(store=QuestionStore(db_path), fleet_home=tmp_path)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(app_mod._question_poller(app, api=api, sleep_fn=sleep))

    assert len(sleep.calls) >= 4, "Loop must keep running after a send error"


def test_poller_records_message_id_mapping(tmp_path: Path) -> None:
    """When send_message_with_id returns a message_id the poller persists the mapping."""
    db_path = tmp_path / "questions.db"
    create_questions_db(db_path)
    insert_question(db_path, qid="q-pre", prompt="pre-existing", created_at=1000.0)
    api = FakeTelegramApi("tok", message_ids=[777])
    sleep = SleepScript(
        stop_after=3,
        hooks={
            1: lambda: insert_question(db_path, qid="q-new", prompt="ask me?", created_at=2000.0)
        },
    )
    app = make_fake_app(store=QuestionStore(db_path), fleet_home=tmp_path)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(app_mod._question_poller(app, api=api, sleep_fn=sleep))

    assert len(api.sent) == 1
    assert "ask me?" in api.sent[0][1]
    mapping_path = tmp_path / "telegram_question_msgs.json"
    assert mapping_path.exists()
    mapping = json.loads(mapping_path.read_text())
    assert mapping.get("777") == "q-new"
