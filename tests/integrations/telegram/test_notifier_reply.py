"""Tests for reply routing and help commands (units under test: commands.py dispatch,
messages.py MessageStore, driven through integrations/telegram/listener.py).

Answer flows get one scripted updates page from ``FakeTelegramApi``; the
question database is a real ``QuestionStore`` on ``tmp_path``.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from fleet.core.config import RuntimeConfig
from fleet.integrations.ask_human.store import QuestionStore
from fleet.integrations.telegram.commands import HELP_TEXT
from fleet.integrations.telegram.messages import MessageStore, OffsetStore
from tests.integrations.telegram.conftest import (
    create_questions_db,
    insert_question,
    run_listener,
    scripted_updates,
)


def test_record_and_lookup_question_message(tmp_path: Path) -> None:
    """Basic round-trip: record then look up."""
    messages = MessageStore(tmp_path / "q_msgs.json")
    messages.record(100, "q-abc")
    assert messages.lookup(100) == "q-abc"
    assert messages.lookup(999) is None


def test_lookup_question_for_message_missing_file(tmp_path: Path) -> None:
    """lookup returns None when the mapping file does not exist."""
    assert MessageStore(tmp_path / "missing.json").lookup(1) is None


def test_record_question_message_caps_at_200(tmp_path: Path) -> None:
    """Oldest entries are evicted when the mapping exceeds 200 entries."""
    path = tmp_path / "q_msgs.json"
    messages = MessageStore(path)
    for i in range(205):
        messages.record(i, f"q-{i}")
    mapping = json.loads(path.read_text())
    assert len(mapping) == 200
    # Oldest 5 entries evicted
    for i in range(5):
        assert str(i) not in mapping
    assert "5" in mapping
    assert "204" in mapping


def test_record_question_message_overwrites_existing_key(tmp_path: Path) -> None:
    """Recording the same message_id twice updates the value."""
    messages = MessageStore(tmp_path / "q_msgs.json")
    messages.record(1, "q-first")
    messages.record(1, "q-second")
    assert messages.lookup(1) == "q-second"


def test_record_question_message_swallows_oserror(tmp_path: Path) -> None:
    """OSError during write is swallowed; function must not raise."""
    # A regular file where the store wants a directory: the write fails
    # with OSError on a real filesystem, no write_text patching needed.
    (tmp_path / "blocker").write_text("not a dir")
    # Must not raise
    MessageStore(tmp_path / "blocker" / "q_msgs.json").record(1, "q-1")


def test_inbound_listener_answer_via_reply_to(tmp_path: Path) -> None:
    """Replying to a question message resolves it and replies 'Answered [agent_id]'."""

    db_path = tmp_path / "questions.db"
    create_questions_db(db_path)
    insert_question(db_path, qid="q-reply", prompt="color?", created_at=1000.0)
    qmsg_path = tmp_path / "qmsgs.json"
    MessageStore(qmsg_path).record(42, "q-reply")

    config = RuntimeConfig(telegram_allowed_ids="123")
    app = MagicMock()
    app.state.fleet_state.config = config

    updates = [
        {
            "update_id": 5,
            "message": {
                "from": {"id": 123},
                "chat": {"id": 123},
                "text": "blue",
                "reply_to_message": {"message_id": 42},
            },
        }
    ]
    api = scripted_updates(updates)

    sent = api.sent
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(run_listener(app, tmp_path, api=api))

    assert len(sent) == 1
    assert "Answered" in sent[0][1]
    assert "test-agent" in sent[0][1] or "q-reply" in sent[0][1]

    question = QuestionStore(db_path).get("q-reply")
    assert question is not None
    assert question.status == "answered"
    assert question.answer == "blue"
    assert OffsetStore(tmp_path / "offset").load() == 6


def test_inbound_listener_reply_to_unknown_mapping(tmp_path: Path) -> None:
    """Reply-to a message not in the mapping replies 'Unknown or expired question'."""
    config = RuntimeConfig(telegram_allowed_ids="123")
    app = MagicMock()
    app.state.fleet_state.config = config

    updates = [
        {
            "update_id": 6,
            "message": {
                "from": {"id": 123},
                "chat": {"id": 123},
                "text": "some answer",
                "reply_to_message": {"message_id": 999},
            },
        }
    ]
    api = scripted_updates(updates)

    # mapping file untouched: _run uses tmp/qmsgs.json, which does not exist here

    sent = api.sent
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(run_listener(app, tmp_path, api=api))

    assert len(sent) == 1
    assert sent[0][1] == "Unknown or expired question"


def test_inbound_listener_reply_to_already_answered(tmp_path: Path) -> None:
    """Reply-to an already-answered question replies 'Question already answered'."""

    db_path = tmp_path / "questions.db"
    create_questions_db(db_path)
    insert_question(db_path, qid="q-done", prompt="done?", created_at=1000.0, status="answered")
    qmsg_path = tmp_path / "qmsgs.json"
    MessageStore(qmsg_path).record(77, "q-done")

    config = RuntimeConfig(telegram_allowed_ids="123")
    app = MagicMock()
    app.state.fleet_state.config = config

    updates = [
        {
            "update_id": 7,
            "message": {
                "from": {"id": 123},
                "chat": {"id": 123},
                "text": "too late",
                "reply_to_message": {"message_id": 77},
            },
        }
    ]
    api = scripted_updates(updates)

    sent = api.sent
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(run_listener(app, tmp_path, api=api))

    assert len(sent) == 1
    assert sent[0][1] == "Question already answered"


def test_inbound_listener_single_pending_fallback(tmp_path: Path) -> None:
    """Plain text with exactly one pending question answers it via fallback."""

    db_path = tmp_path / "questions.db"
    create_questions_db(db_path)
    insert_question(db_path, qid="q-one", prompt="scale?", created_at=1000.0)
    config = RuntimeConfig(telegram_allowed_ids="123")
    app = MagicMock()
    app.state.fleet_state.config = config

    updates = [
        {
            "update_id": 8,
            "message": {
                "from": {"id": 123},
                "chat": {"id": 123},
                "text": "fine thanks",
            },
        }
    ]
    api = scripted_updates(updates)

    sent = api.sent
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(run_listener(app, tmp_path, api=api))

    assert len(sent) == 1
    assert "Answered" in sent[0][1]

    question = QuestionStore(db_path).get("q-one")
    assert question is not None
    assert question.status == "answered"
    assert question.answer == "fine thanks"


def test_inbound_listener_multiple_pending_reply(tmp_path: Path) -> None:
    """Plain text with multiple pending questions sends a count hint."""

    db_path = tmp_path / "questions.db"
    create_questions_db(db_path)
    insert_question(db_path, qid="q-a", prompt="first?", created_at=1000.0)
    insert_question(db_path, qid="q-b", prompt="second?", created_at=1001.0)
    config = RuntimeConfig(telegram_allowed_ids="123")
    app = MagicMock()
    app.state.fleet_state.config = config

    updates = [
        {
            "update_id": 9,
            "message": {
                "from": {"id": 123},
                "chat": {"id": 123},
                "text": "hello",
            },
        }
    ]
    api = scripted_updates(updates)

    sent = api.sent
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(run_listener(app, tmp_path, api=api))

    assert len(sent) == 1
    assert "2 questions pending" in sent[0][1]
    assert "reply directly" in sent[0][1]


def test_inbound_listener_zero_pending_silently_dropped(tmp_path: Path) -> None:
    """Plain text with no pending questions is silently dropped."""

    db_path = tmp_path / "questions.db"
    create_questions_db(db_path)
    config = RuntimeConfig(telegram_allowed_ids="123")
    app = MagicMock()
    app.state.fleet_state.config = config

    updates = [
        {
            "update_id": 10,
            "message": {
                "from": {"id": 123},
                "chat": {"id": 123},
                "text": "just chatting",
            },
        }
    ]
    api = scripted_updates(updates)

    sent = api.sent
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(run_listener(app, tmp_path, api=api))

    assert sent == [], "No reply sent when there are no pending questions"


def test_inbound_listener_numeric_option_shortcut(tmp_path: Path) -> None:
    """Bare integer text picks the matching option string from the question's options list."""

    db_path = tmp_path / "questions.db"
    create_questions_db(db_path)
    insert_question(
        db_path,
        qid="q-opt",
        prompt="pick one?",
        created_at=1000.0,
        options=["alpha", "beta", "gamma"],
        agent_id="agent-opts",
    )
    qmsg_path = tmp_path / "qmsgs.json"
    MessageStore(qmsg_path).record(55, "q-opt")

    config = RuntimeConfig(telegram_allowed_ids="123")
    app = MagicMock()
    app.state.fleet_state.config = config

    updates = [
        {
            "update_id": 11,
            "message": {
                "from": {"id": 123},
                "chat": {"id": 123},
                "text": "2",
                "reply_to_message": {"message_id": 55},
            },
        }
    ]
    api = scripted_updates(updates)

    sent = api.sent
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(run_listener(app, tmp_path, api=api))

    assert len(sent) == 1
    assert "Answered" in sent[0][1]
    assert "agent-opts" in sent[0][1]

    question = QuestionStore(db_path).get("q-opt")
    assert question is not None
    assert question.answer == "beta"


def test_inbound_listener_numeric_out_of_range_stored_as_string(tmp_path: Path) -> None:
    """Integer text out of options range is stored as the raw string, not an option."""

    db_path = tmp_path / "questions.db"
    create_questions_db(db_path)
    insert_question(
        db_path,
        qid="q-out",
        prompt="pick?",
        created_at=1000.0,
        options=["x", "y"],
        agent_id="agent-out",
    )
    qmsg_path = tmp_path / "qmsgs.json"
    MessageStore(qmsg_path).record(88, "q-out")

    config = RuntimeConfig(telegram_allowed_ids="123")
    app = MagicMock()
    app.state.fleet_state.config = config

    updates = [
        {
            "update_id": 12,
            "message": {
                "from": {"id": 123},
                "chat": {"id": 123},
                "text": "99",
                "reply_to_message": {"message_id": 88},
            },
        }
    ]
    api = scripted_updates(updates)

    sent = api.sent
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(run_listener(app, tmp_path, api=api))

    assert len(sent) == 1
    assert "Answered" in sent[0][1]

    question = QuestionStore(db_path).get("q-out")
    assert question is not None
    assert question.answer == "99"  # stored as raw string, not option


def test_inbound_listener_help_replies_with_help_text(tmp_path: Path) -> None:
    """/help replies with HELP_TEXT."""
    config = RuntimeConfig(telegram_allowed_ids="123")
    app = MagicMock()
    app.state.fleet_state.config = config

    updates = [
        {"update_id": 100, "message": {"from": {"id": 123}, "chat": {"id": 123}, "text": "/help"}}
    ]
    api = scripted_updates(updates)

    sent = api.sent
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(run_listener(app, tmp_path, api=api))

    assert len(sent) == 1
    assert sent[0][1] == HELP_TEXT


def test_inbound_listener_start_replies_with_help_text(tmp_path: Path) -> None:
    """/start replies with the same HELP_TEXT as /help."""
    config = RuntimeConfig(telegram_allowed_ids="123")
    app = MagicMock()
    app.state.fleet_state.config = config

    updates = [
        {"update_id": 101, "message": {"from": {"id": 123}, "chat": {"id": 123}, "text": "/start"}}
    ]
    api = scripted_updates(updates)

    sent = api.sent
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(run_listener(app, tmp_path, api=api))

    assert len(sent) == 1
    assert sent[0][1] == HELP_TEXT


def test_inbound_listener_help_botname_replies_with_help_text(tmp_path: Path) -> None:
    """/help@botname replies with HELP_TEXT via the existing @-strip."""
    config = RuntimeConfig(telegram_allowed_ids="123")
    app = MagicMock()
    app.state.fleet_state.config = config

    updates = [
        {
            "update_id": 102,
            "message": {"from": {"id": 123}, "chat": {"id": 123}, "text": "/help@myfleetbot"},
        }
    ]
    api = scripted_updates(updates)

    sent = api.sent
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(run_listener(app, tmp_path, api=api))

    assert len(sent) == 1
    assert sent[0][1] == HELP_TEXT


def test_inbound_listener_help_rejected_sender_no_reply(tmp_path: Path) -> None:
    """/help from a non-allowlisted sender gets no reply (security gate)."""
    config = RuntimeConfig(telegram_allowed_ids="999")  # only 999 allowed
    app = MagicMock()
    app.state.fleet_state.config = config

    updates = [
        {"update_id": 103, "message": {"from": {"id": 111}, "chat": {"id": 111}, "text": "/help"}}
    ]
    api = scripted_updates(updates)

    sent = api.sent
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(run_listener(app, tmp_path, api=api))

    assert sent == [], "Rejected sender must get no reply for /help"


def test_inbound_listener_slash_command_not_intercepted_by_fallback(tmp_path: Path) -> None:
    """/start replies with help text and does not trigger the answer fallback."""

    db_path = tmp_path / "questions.db"
    create_questions_db(db_path)
    insert_question(db_path, qid="q-cmd", prompt="pending?", created_at=1000.0)
    config = RuntimeConfig(telegram_allowed_ids="123")
    app = MagicMock()
    app.state.fleet_state.config = config

    updates = [
        {
            "update_id": 13,
            "message": {
                "from": {"id": 123},
                "chat": {"id": 123},
                "text": "/start",
            },
        }
    ]
    api = scripted_updates(updates)

    sent = api.sent
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(run_listener(app, tmp_path, api=api))

    assert len(sent) == 1
    assert sent[0][1] == HELP_TEXT, "/start must reply with help text"

    question = QuestionStore(db_path).get("q-cmd")
    assert question is not None
    assert question.status == "pending", "Question must remain pending after /start"
