"""Tests for Telegram notifier, question poller, and config round-trip."""
from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import fleet.telegram as tg
from fleet.config import load, write_atomic
from fleet.schemas import RuntimeConfig


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
) -> None:
    conn = sqlite3.connect(str(path))
    conn.execute(
        "INSERT INTO questions (id, agent_id, prompt, created_at, status) VALUES (?, ?, ?, ?, ?)",
        (qid, "test-agent", prompt, created_at, status),
    )
    conn.commit()
    conn.close()


def _make_fake_app(chat_id: str = "999") -> MagicMock:
    cfg = RuntimeConfig(telegram_chat_id=chat_id)
    fake_app = MagicMock()
    fake_app.state.fleet_state.config = cfg
    return fake_app


class _FakeResp:
    def read(self) -> bytes:
        return b""

    def __enter__(self) -> "_FakeResp":
        return self

    def __exit__(self, *a: object) -> None:
        pass


# ---------------------------------------------------------------------------
# Notifier tests
# ---------------------------------------------------------------------------

def test_send_message_posts_correct_url_and_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    """send_message POSTs to the correct Bot API URL with the right JSON payload."""
    captured: list = []

    def _fake_urlopen(req, timeout=None):
        captured.append(req)
        return _FakeResp()

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)
    asyncio.run(tg.send_message("mytoken", "123", "hello"))

    assert len(captured) == 1
    req = captured[0]
    assert req.full_url == "https://api.telegram.org/botmytoken/sendMessage"
    body = json.loads(req.data.decode())
    assert body == {"chat_id": "123", "text": "hello"}


def test_send_message_truncates_to_4096_chars(monkeypatch: pytest.MonkeyPatch) -> None:
    """send_message silently truncates text to 4096 characters."""
    captured_texts: list[str] = []

    def _fake_urlopen(req, timeout=None):
        captured_texts.append(json.loads(req.data.decode())["text"])
        return _FakeResp()

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)
    asyncio.run(tg.send_message("tok", "cid", "a" * 5000))

    assert len(captured_texts) == 1
    assert len(captured_texts[0]) == 4096


def test_send_message_swallows_exception_and_does_not_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    """send_message never raises; HTTP errors are swallowed."""
    def _fake_urlopen(req, timeout=None):
        raise OSError("connection refused")

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)
    asyncio.run(tg.send_message("tok", "cid", "hi"))  # must not raise


def test_is_configured_false_without_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """is_configured() returns False when TELEGRAM_BOT_TOKEN is unset."""
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    assert not tg.is_configured()


def test_is_configured_true_with_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """is_configured() returns True when TELEGRAM_BOT_TOKEN is set."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    assert tg.is_configured()


def test_poller_skips_send_when_token_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No HTTP call is made when TELEGRAM_BOT_TOKEN is absent (silent no-op)."""
    db_path = tmp_path / "questions.db"
    _create_questions_db(db_path)

    import fleet.serve.app as app_mod
    import fleet.serve.routes.chat as chat_mod

    monkeypatch.setattr(app_mod, "ASK_HUMAN_DB", db_path)
    monkeypatch.setattr(chat_mod, "ASK_HUMAN_DB", db_path)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)

    sent: list[str] = []

    async def _fake_send(token: str, chat_id: str, text: str) -> None:
        sent.append(text)

    monkeypatch.setattr(tg, "send_message", _fake_send)

    call_n = [0]

    async def _fake_sleep(s: float) -> None:
        call_n[0] += 1
        if call_n[0] == 1:
            _insert_question(db_path, qid="q1", prompt="should not send", created_at=500.0)
        elif call_n[0] >= 2:
            raise asyncio.CancelledError()

    monkeypatch.setattr(asyncio, "sleep", _fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(app_mod._question_poller(_make_fake_app()))

    assert sent == [], "No messages should be sent when token is absent"


# ---------------------------------------------------------------------------
# Poller tests
# ---------------------------------------------------------------------------

def test_poller_does_not_send_preexisting_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pre-existing pending rows at startup are NOT sent (watermark baseline)."""
    db_path = tmp_path / "questions.db"
    _create_questions_db(db_path)
    _insert_question(db_path, qid="q-pre", prompt="old question", created_at=1000.0)

    import fleet.serve.app as app_mod
    import fleet.serve.routes.chat as chat_mod

    monkeypatch.setattr(app_mod, "ASK_HUMAN_DB", db_path)
    monkeypatch.setattr(chat_mod, "ASK_HUMAN_DB", db_path)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")

    sent: list[str] = []

    async def _fake_send(token: str, chat_id: str, text: str) -> None:
        sent.append(text)

    monkeypatch.setattr(tg, "send_message", _fake_send)

    call_n = [0]

    async def _fake_sleep(s: float) -> None:
        call_n[0] += 1
        if call_n[0] >= 2:
            raise asyncio.CancelledError()

    monkeypatch.setattr(asyncio, "sleep", _fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(app_mod._question_poller(_make_fake_app()))

    assert sent == [], "Pre-existing rows must not be sent"


def test_poller_sends_new_question_exactly_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A newly inserted pending row is sent exactly once."""
    db_path = tmp_path / "questions.db"
    _create_questions_db(db_path)
    _insert_question(db_path, qid="q-pre", prompt="pre-existing", created_at=1000.0)

    import fleet.serve.app as app_mod
    import fleet.serve.routes.chat as chat_mod

    monkeypatch.setattr(app_mod, "ASK_HUMAN_DB", db_path)
    monkeypatch.setattr(chat_mod, "ASK_HUMAN_DB", db_path)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")

    sent: list[str] = []

    async def _fake_send(token: str, chat_id: str, text: str) -> None:
        sent.append(text)

    monkeypatch.setattr(tg, "send_message", _fake_send)

    call_n = [0]

    async def _fake_sleep(s: float) -> None:
        call_n[0] += 1
        if call_n[0] == 1:
            # Insert new row after watermark is established
            _insert_question(db_path, qid="q-new", prompt="new question?", created_at=2000.0)
        elif call_n[0] >= 3:
            raise asyncio.CancelledError()

    monkeypatch.setattr(asyncio, "sleep", _fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(app_mod._question_poller(_make_fake_app()))

    assert len(sent) == 1
    assert "new question?" in sent[0]


def test_poller_continues_after_send_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A send error does not kill the poll loop."""
    db_path = tmp_path / "questions.db"
    _create_questions_db(db_path)  # empty → watermark = 0.0

    import fleet.serve.app as app_mod
    import fleet.serve.routes.chat as chat_mod

    monkeypatch.setattr(app_mod, "ASK_HUMAN_DB", db_path)
    monkeypatch.setattr(chat_mod, "ASK_HUMAN_DB", db_path)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")

    async def _failing_send(token: str, chat_id: str, text: str) -> None:
        raise RuntimeError("network boom")

    monkeypatch.setattr(tg, "send_message", _failing_send)

    call_n = [0]

    async def _fake_sleep(s: float) -> None:
        call_n[0] += 1
        if call_n[0] == 1:
            # Insert row so send_message is called (and fails)
            _insert_question(db_path, qid="q1", prompt="failing", created_at=500.0)
        elif call_n[0] >= 4:
            raise asyncio.CancelledError()

    monkeypatch.setattr(asyncio, "sleep", _fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(app_mod._question_poller(_make_fake_app()))

    assert call_n[0] >= 4, "Loop must keep running after a send error"


# ---------------------------------------------------------------------------
# Config round-trip
# ---------------------------------------------------------------------------

def test_telegram_chat_id_round_trips(tmp_path: Path) -> None:
    """telegram_chat_id persists through write_atomic and is readable via load."""
    cfg_path = tmp_path / "runtime.toml"
    load(cfg_path)

    result = write_atomic(cfg_path, {"telegram_chat_id": "my-channel-id"})
    assert result.telegram_chat_id == "my-channel-id"

    reloaded = load(cfg_path)
    assert reloaded.telegram_chat_id == "my-channel-id"


def test_telegram_chat_id_default_is_empty_string(tmp_path: Path) -> None:
    """telegram_chat_id defaults to empty string in a freshly created config."""
    cfg_path = tmp_path / "runtime.toml"
    cfg = load(cfg_path)
    assert cfg.telegram_chat_id == ""
