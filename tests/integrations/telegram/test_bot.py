"""Tests for the Telegram answer interface: mapping store, send_message_with_id, inbound flows."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import fleet.integrations.telegram.listener as listener_mod
from fleet.core.config import RuntimeConfig
from fleet.core.task import Task
from fleet.integrations.ask_human.store import QuestionStore
from fleet.integrations.telegram.api import TelegramApi
from fleet.integrations.telegram.commands import CommandEnv, parse_allowed_ids
from fleet.integrations.telegram.listener import inbound_listener
from fleet.integrations.telegram.messages import MessageStore, OffsetStore

# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def _create_questions_db(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    conn.execute(
        """
        CREATE TABLE questions (
            id TEXT PRIMARY KEY,
            agent_id TEXT,
            session_id TEXT,
            prompt TEXT,
            options TEXT,
            multi_select INTEGER DEFAULT 0,
            priority INTEGER DEFAULT 0,
            created_at REAL,
            timeout_s REAL,
            default_answer TEXT,
            status TEXT DEFAULT 'pending',
            answer TEXT,
            note TEXT,
            answered_by TEXT,
            answered_at REAL
        )
        """
    )
    conn.commit()
    conn.close()


def _insert_question(
    path: Path,
    *,
    qid: str,
    prompt: str,
    created_at: float,
    status: str = "pending",
    answer: str | None = None,
    options: list | None = None,
    agent_id: str = "test-agent",
) -> None:
    conn = sqlite3.connect(str(path))
    conn.execute(
        "INSERT INTO questions (id, agent_id, prompt, created_at, status, answer, options) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            qid,
            agent_id,
            prompt,
            created_at,
            status,
            answer,
            json.dumps(options) if options is not None else None,
        ),
    )
    conn.commit()
    conn.close()


def _make_fake_app(allowed_ids: str = "123", default_cwd: str = "") -> MagicMock:
    cfg = RuntimeConfig(telegram_allowed_ids=allowed_ids, telegram_default_cwd=default_cwd)
    app = MagicMock()
    app.state.fleet_state.config = cfg
    return app


def _listener_parts(
    app: MagicMock, tmp_path: Path, *, qmsgs: str = "qmsgs.json", db: Path | None = None
) -> tuple[TelegramApi, QuestionStore, CommandEnv, OffsetStore]:
    """Build (api, store, env, offsets) for inbound_listener from the fake app."""
    cfg = app.state.fleet_state.config
    return (
        TelegramApi("tok"),
        QuestionStore(db or tmp_path / "questions.db"),
        CommandEnv(
            queue=app.state.queue,
            messages=MessageStore(tmp_path / qmsgs),
            allowed_ids=lambda: parse_allowed_ids(cfg.telegram_allowed_ids),
            default_cwd=lambda: cfg.telegram_default_cwd or None,
        ),
        OffsetStore(tmp_path / "offset"),
    )


def _run(app: MagicMock, tmp_path: Path) -> None:
    """Build listener parts from the fake app and drive until CancelledError."""
    api, store, env, offsets = _listener_parts(app, tmp_path)
    return asyncio.run(inbound_listener(api, store, env, offsets))


def _make_fetch_dispatcher(updates: list) -> object:
    """Fake asyncio.to_thread: returns updates on 1st _fetch_updates call,
    CancelledError on 2nd; executes fn(*args) for all other functions."""
    fetch_n = [0]

    async def _fake(fn, *args, **kwargs):  # type: ignore[misc]
        if fn is listener_mod._fetch_updates:
            fetch_n[0] += 1
            if fetch_n[0] == 1:
                return updates
            raise asyncio.CancelledError()
        return fn(*args, **kwargs)

    return _fake


class _JsonResp:
    """Minimal urllib response stub that returns a JSON body."""

    def __init__(self, body: dict) -> None:
        self._data = json.dumps(body).encode()

    def read(self) -> bytes:
        return self._data

    def __enter__(self) -> _JsonResp:
        return self

    def __exit__(self, *a: object) -> None:
        pass


# ---------------------------------------------------------------------------
# (a) Mapping store: record_question_message / lookup_question_for_message
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# (b) send_message_with_id
# ---------------------------------------------------------------------------


def test_send_message_with_id_returns_message_id(monkeypatch: pytest.MonkeyPatch) -> None:
    """Returns the integer message_id parsed from a successful sendMessage response."""
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda req, timeout=None: _JsonResp({"ok": True, "result": {"message_id": 77}}),
    )
    result = asyncio.run(TelegramApi("tok").send_with_id("123", "hello"))
    assert result == 77


def test_send_message_with_id_returns_none_on_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Returns None when the HTTP call raises an exception."""
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda req, timeout=None: (_ for _ in ()).throw(OSError("connection refused")),
    )
    assert asyncio.run(TelegramApi("tok").send_with_id("123", "hi")) is None


def test_send_message_with_id_returns_none_when_ok_false(monkeypatch: pytest.MonkeyPatch) -> None:
    """Returns None when Telegram responds with ok=false."""
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda req, timeout=None: _JsonResp({"ok": False, "description": "Bad Request"}),
    )
    assert asyncio.run(TelegramApi("tok").send_with_id("123", "hi")) is None


# ---------------------------------------------------------------------------
# (c) Listener answer flows
# ---------------------------------------------------------------------------


def test_reply_to_mapped_message_answers_question(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reply-to a mapped message: status=answered, answer JSON-encoded, answered_by=telegram."""

    db_path = tmp_path / "questions.db"
    _create_questions_db(db_path)
    _insert_question(db_path, qid="q-1", prompt="color?", created_at=1000.0, agent_id="my-agent")

    qmsg_path = tmp_path / "qmsgs.json"
    MessageStore(qmsg_path).record(42, "q-1")

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    app = _make_fake_app()

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

    sent: list[tuple[str, str]] = []

    async def _fake_send(self, chat_id: str, text: str) -> None:
        sent.append((chat_id, text))

    monkeypatch.setattr(asyncio, "to_thread", _make_fetch_dispatcher(updates))
    monkeypatch.setattr(TelegramApi, "send", _fake_send)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(_run(app, tmp_path))

    assert len(sent) == 1
    assert "Answered" in sent[0][1]

    conn = sqlite3.connect(str(db_path))
    row = conn.execute(
        "SELECT status, answer, answered_by FROM questions WHERE id='q-1'"
    ).fetchone()
    conn.close()
    assert row[0] == "answered"
    assert json.loads(row[1]) == "blue"
    assert row[2] == "telegram"


def test_plain_text_one_pending_answers_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Plain text with exactly one pending question answers that question."""

    db_path = tmp_path / "questions.db"
    _create_questions_db(db_path)
    _insert_question(db_path, qid="q-only", prompt="confirm?", created_at=1000.0)

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    app = _make_fake_app()

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

    sent: list[str] = []

    async def _fake_send(self, chat_id: str, text: str) -> None:
        sent.append(text)

    monkeypatch.setattr(asyncio, "to_thread", _make_fetch_dispatcher(updates))
    monkeypatch.setattr(TelegramApi, "send", _fake_send)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(_run(app, tmp_path))

    assert len(sent) == 1
    assert "Answered" in sent[0]

    conn = sqlite3.connect(str(db_path))
    row = conn.execute("SELECT status, answer FROM questions WHERE id='q-only'").fetchone()
    conn.close()
    assert row[0] == "answered"
    assert json.loads(row[1]) == "yes"


def test_plain_text_two_pending_sends_hint_no_db_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Plain text with two pending questions sends the hint message; neither is answered."""

    db_path = tmp_path / "questions.db"
    _create_questions_db(db_path)
    _insert_question(db_path, qid="q-a", prompt="first?", created_at=1000.0)
    _insert_question(db_path, qid="q-b", prompt="second?", created_at=1001.0)

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    app = _make_fake_app()

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

    sent: list[str] = []

    async def _fake_send(self, chat_id: str, text: str) -> None:
        sent.append(text)

    monkeypatch.setattr(asyncio, "to_thread", _make_fetch_dispatcher(updates))
    monkeypatch.setattr(TelegramApi, "send", _fake_send)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(_run(app, tmp_path))

    assert len(sent) == 1
    assert "2 questions pending" in sent[0]
    assert "reply directly" in sent[0]

    conn = sqlite3.connect(str(db_path))
    rows = conn.execute("SELECT status FROM questions WHERE status='pending'").fetchall()
    conn.close()
    assert len(rows) == 2, "Both questions must remain pending"


def test_numeric_reply_with_options_stores_option_string(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bare integer '2' via reply-to resolves to option[1] ('beta') and stores that string."""

    db_path = tmp_path / "questions.db"
    _create_questions_db(db_path)
    _insert_question(
        db_path,
        qid="q-opts",
        prompt="pick one?",
        created_at=1000.0,
        options=["alpha", "beta", "gamma"],
        agent_id="opts-agent",
    )
    qmsg_path = tmp_path / "qmsgs.json"
    MessageStore(qmsg_path).record(55, "q-opts")

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    app = _make_fake_app()

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

    sent: list[str] = []

    async def _fake_send(self, chat_id: str, text: str) -> None:
        sent.append(text)

    monkeypatch.setattr(asyncio, "to_thread", _make_fetch_dispatcher(updates))
    monkeypatch.setattr(TelegramApi, "send", _fake_send)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(_run(app, tmp_path))

    assert len(sent) == 1
    assert "Answered" in sent[0]

    conn = sqlite3.connect(str(db_path))
    row = conn.execute("SELECT answer FROM questions WHERE id='q-opts'").fetchone()
    conn.close()
    assert json.loads(row[0]) == "beta"


def test_sender_not_on_allowlist_rejected_no_db_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An update from a sender not in the allowlist is rejected; the question is not touched."""

    db_path = tmp_path / "questions.db"
    _create_questions_db(db_path)
    _insert_question(db_path, qid="q-safe", prompt="stay pending?", created_at=1000.0)
    qmsg_path = tmp_path / "qmsgs.json"
    MessageStore(qmsg_path).record(99, "q-safe")

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    # Allowed only: 999; sender is 111
    app = _make_fake_app(allowed_ids="999")

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

    sent: list[str] = []

    async def _fake_send(self, chat_id: str, text: str) -> None:
        sent.append(text)

    monkeypatch.setattr(asyncio, "to_thread", _make_fetch_dispatcher(updates))
    monkeypatch.setattr(TelegramApi, "send", _fake_send)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(_run(app, tmp_path))

    assert sent == [], "No reply to a rejected sender"

    conn = sqlite3.connect(str(db_path))
    row = conn.execute("SELECT status FROM questions WHERE id='q-safe'").fetchone()
    conn.close()
    assert row[0] == "pending", "Question must remain pending after rejected sender"


def test_already_answered_conflict_reply_no_overwrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A second answer is rejected ('already answered'); the first answer stands."""

    db_path = tmp_path / "questions.db"
    _create_questions_db(db_path)
    _insert_question(
        db_path,
        qid="q-done",
        prompt="done?",
        created_at=1000.0,
        status="answered",
        answer=json.dumps("original answer"),
    )
    qmsg_path = tmp_path / "qmsgs.json"
    MessageStore(qmsg_path).record(77, "q-done")

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    app = _make_fake_app()

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

    sent: list[str] = []

    async def _fake_send(self, chat_id: str, text: str) -> None:
        sent.append(text)

    monkeypatch.setattr(asyncio, "to_thread", _make_fetch_dispatcher(updates))
    monkeypatch.setattr(TelegramApi, "send", _fake_send)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(_run(app, tmp_path))

    assert len(sent) == 1
    assert sent[0] == "Question already answered"

    conn = sqlite3.connect(str(db_path))
    row = conn.execute("SELECT answer FROM questions WHERE id='q-done'").fetchone()
    conn.close()
    assert json.loads(row[0]) == "original answer", "Existing answer must not be overwritten"


def test_task_command_creates_task_regression(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """/new_task still creates a task when the answer interface is wired (regression)."""

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    app = _make_fake_app()
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

    sent: list[tuple[str, str]] = []

    async def _fake_send(self, chat_id: str, text: str) -> None:
        sent.append((chat_id, text))

    call_n = [0]

    async def _fake_to_thread(fn, *args):
        call_n[0] += 1
        if fn is listener_mod._fetch_updates:
            if call_n[0] == 1:
                return updates
            raise asyncio.CancelledError()
        return fn(*args)

    monkeypatch.setattr(asyncio, "to_thread", _fake_to_thread)
    monkeypatch.setattr(TelegramApi, "send", _fake_send)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(_run(app, tmp_path))

    app.state.queue.create_task.assert_called_once()
    assert len(sent) == 1
    assert "fleet-reg1" in sent[0][1]
