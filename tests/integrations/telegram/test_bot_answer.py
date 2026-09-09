"""Tests for the Telegram answer interface flows (unit under test: commands.py dispatch,
driven through integrations/telegram/listener.py).

Updates come from a scripted ``FakeTelegramApi``; the question database is a
real ``QuestionStore`` on ``tmp_path`` verified through its typed ``get``.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from fleet.core.task import Task
from fleet.integrations.ask_human.store import QuestionStore
from fleet.integrations.telegram.messages import MessageStore
from tests.integrations.telegram.conftest import (
    create_questions_db,
    insert_question,
    make_fake_app,
    run_listener,
    scripted_updates,
)


def test_reply_to_mapped_message_answers_question(tmp_path: Path) -> None:
    """Reply-to a mapped message: status=answered, answer JSON-encoded, answered_by=telegram."""

    db_path = tmp_path / "questions.db"
    create_questions_db(db_path)
    insert_question(db_path, qid="q-1", prompt="color?", created_at=1000.0, agent_id="my-agent")

    qmsg_path = tmp_path / "qmsgs.json"
    MessageStore(qmsg_path).record(42, "q-1")

    app = make_fake_app(allowed_ids="123")

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

    question = QuestionStore(db_path).get("q-1")
    assert question is not None
    assert question.status == "answered"
    assert question.answer == "blue"
    assert question.answered_by == "telegram"


def test_plain_text_one_pending_answers_it(tmp_path: Path) -> None:
    """Plain text with exactly one pending question answers that question."""

    db_path = tmp_path / "questions.db"
    create_questions_db(db_path)
    insert_question(db_path, qid="q-only", prompt="confirm?", created_at=1000.0)

    app = make_fake_app(allowed_ids="123")

    updates = [
        {
            "update_id": 8,
            "message": {
                "from": {"id": 123},
                "chat": {"id": 123},
                "text": "yes",
            },
        }
    ]
    api = scripted_updates(updates)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(run_listener(app, tmp_path, api=api))
    sent = [text for _, text in api.sent]

    assert len(sent) == 1
    assert "Answered" in sent[0]

    question = QuestionStore(db_path).get("q-only")
    assert question is not None
    assert question.status == "answered"
    assert question.answer == "yes"


def test_plain_text_two_pending_sends_hint_no_db_write(tmp_path: Path) -> None:
    """Plain text with two pending questions sends the hint message; neither is answered."""

    db_path = tmp_path / "questions.db"
    create_questions_db(db_path)
    insert_question(db_path, qid="q-a", prompt="first?", created_at=1000.0)
    insert_question(db_path, qid="q-b", prompt="second?", created_at=1001.0)

    app = make_fake_app(allowed_ids="123")

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

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(run_listener(app, tmp_path, api=api))
    sent = [text for _, text in api.sent]

    assert len(sent) == 1
    assert "2 questions pending" in sent[0]
    assert "reply directly" in sent[0]

    store = QuestionStore(db_path)
    assert len(store.list_pending()) == 2, "Both questions must remain pending"


def test_numeric_reply_with_options_stores_option_string(tmp_path: Path) -> None:
    """Bare integer '2' via reply-to resolves to option[1] ('beta') and stores that string."""

    db_path = tmp_path / "questions.db"
    create_questions_db(db_path)
    insert_question(
        db_path,
        qid="q-opts",
        prompt="pick one?",
        created_at=1000.0,
        options=["alpha", "beta", "gamma"],
        agent_id="opts-agent",
    )
    qmsg_path = tmp_path / "qmsgs.json"
    MessageStore(qmsg_path).record(55, "q-opts")

    app = make_fake_app(allowed_ids="123")

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

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(run_listener(app, tmp_path, api=api))
    sent = [text for _, text in api.sent]

    assert len(sent) == 1
    assert "Answered" in sent[0]

    question = QuestionStore(db_path).get("q-opts")
    assert question is not None
    assert question.answer == "beta"


def test_sender_not_on_allowlist_rejected_no_db_write(tmp_path: Path) -> None:
    """An update from a sender not in the allowlist is rejected; the question is not touched."""

    db_path = tmp_path / "questions.db"
    create_questions_db(db_path)
    insert_question(db_path, qid="q-safe", prompt="stay pending?", created_at=1000.0)
    qmsg_path = tmp_path / "qmsgs.json"
    MessageStore(qmsg_path).record(99, "q-safe")

    # Allowed only: 999; sender is 111
    app = make_fake_app(allowed_ids="999")

    updates = [
        {
            "update_id": 20,
            "message": {
                "from": {"id": 111},
                "chat": {"id": 111},
                "text": "hacked",
                "reply_to_message": {"message_id": 99},
            },
        }
    ]
    api = scripted_updates(updates)

    sent = api.sent
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(run_listener(app, tmp_path, api=api))

    assert sent == [], "No reply to a rejected sender"

    question = QuestionStore(db_path).get("q-safe")
    assert question is not None
    assert question.status == "pending", "Question must remain pending after rejected sender"


def test_already_answered_conflict_reply_no_overwrite(tmp_path: Path) -> None:
    """A second answer is rejected ('already answered'); the first answer stands."""

    db_path = tmp_path / "questions.db"
    create_questions_db(db_path)
    insert_question(
        db_path,
        qid="q-done",
        prompt="done?",
        created_at=1000.0,
        status="answered",
        answer=json.dumps("original answer"),
    )
    qmsg_path = tmp_path / "qmsgs.json"
    MessageStore(qmsg_path).record(77, "q-done")

    app = make_fake_app(allowed_ids="123")

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

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(run_listener(app, tmp_path, api=api))
    sent = [text for _, text in api.sent]

    assert len(sent) == 1
    assert sent[0] == "Question already answered"

    question = QuestionStore(db_path).get("q-done")
    assert question is not None
    assert question.answer == "original answer", "Existing answer must not be overwritten"


def test_task_command_creates_task_regression(tmp_path: Path) -> None:
    """/new_task still creates a task when the answer interface is wired (regression)."""

    app = make_fake_app(allowed_ids="123")
    fake_task = Task(id="fleet-reg1", title="Regression check", description=None, status="open")
    app.state.queue.create_task.return_value = fake_task

    updates = [
        {
            "update_id": 30,
            "message": {
                "from": {"id": 123},
                "chat": {"id": 123},
                "text": "/new_task Regression check",
            },
        }
    ]
    api = scripted_updates(updates)

    sent = api.sent
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(run_listener(app, tmp_path, api=api))

    app.state.queue.create_task.assert_called_once()
    assert len(sent) == 1
    assert "fleet-reg1" in sent[0][1]
