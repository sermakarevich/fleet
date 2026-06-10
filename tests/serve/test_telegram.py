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


# ---------------------------------------------------------------------------
# New config fields round-trip
# ---------------------------------------------------------------------------

def test_telegram_allowed_ids_default_is_empty_string(tmp_path: Path) -> None:
    cfg = load(tmp_path / "runtime.toml")
    assert cfg.telegram_allowed_ids == ""


def test_telegram_default_cwd_default_is_empty_string(tmp_path: Path) -> None:
    cfg = load(tmp_path / "runtime.toml")
    assert cfg.telegram_default_cwd == ""


def test_telegram_allowed_ids_round_trips(tmp_path: Path) -> None:
    cfg_path = tmp_path / "runtime.toml"
    load(cfg_path)
    result = write_atomic(cfg_path, {"telegram_allowed_ids": "111,222,333"})
    assert result.telegram_allowed_ids == "111,222,333"
    assert load(cfg_path).telegram_allowed_ids == "111,222,333"


def test_telegram_default_cwd_round_trips(tmp_path: Path) -> None:
    cfg_path = tmp_path / "runtime.toml"
    load(cfg_path)
    result = write_atomic(cfg_path, {"telegram_default_cwd": "/home/user/project"})
    assert result.telegram_default_cwd == "/home/user/project"
    assert load(cfg_path).telegram_default_cwd == "/home/user/project"


# ---------------------------------------------------------------------------
# _parse_allowed_ids
# ---------------------------------------------------------------------------

def test_parse_allowed_ids_empty_string() -> None:
    assert tg._parse_allowed_ids("") == set()


def test_parse_allowed_ids_single() -> None:
    assert tg._parse_allowed_ids("12345") == {"12345"}


def test_parse_allowed_ids_comma_separated() -> None:
    assert tg._parse_allowed_ids("111, 222 , 333") == {"111", "222", "333"}


def test_parse_allowed_ids_ignores_empty_segments() -> None:
    assert tg._parse_allowed_ids(",,,  ") == set()


# ---------------------------------------------------------------------------
# _is_allowed
# ---------------------------------------------------------------------------

def _make_update(from_id: str | None = None, chat_id: str | None = None) -> dict:
    msg: dict = {}
    if from_id is not None:
        msg["from"] = {"id": int(from_id)}
    if chat_id is not None:
        msg["chat"] = {"id": int(chat_id)}
    return {"update_id": 1, "message": msg}


def test_is_allowed_from_id_in_list() -> None:
    assert tg._is_allowed(_make_update(from_id="123"), {"123"})


def test_is_allowed_chat_id_in_list() -> None:
    assert tg._is_allowed(_make_update(chat_id="-100987"), {"-100987"})


def test_is_allowed_neither_in_list() -> None:
    assert not tg._is_allowed(_make_update(from_id="111", chat_id="222"), {"999"})


def test_is_allowed_empty_allowlist() -> None:
    assert not tg._is_allowed(_make_update(from_id="123", chat_id="123"), set())


def test_is_allowed_no_ids_in_update() -> None:
    assert not tg._is_allowed({"update_id": 1, "message": {}}, {"123"})


# ---------------------------------------------------------------------------
# _parse_task_command
# ---------------------------------------------------------------------------

def test_parse_task_command_simple() -> None:
    assert tg._parse_task_command("/task Fix the bug") == ("Fix the bug", None)


def test_parse_task_command_with_description() -> None:
    result = tg._parse_task_command("/task Fix the bug\nDetails here\nMore info")
    assert result == ("Fix the bug", "Details here\nMore info")


def test_parse_task_command_not_a_task() -> None:
    assert tg._parse_task_command("/start") is None
    assert tg._parse_task_command("Hello world") is None


def test_parse_task_command_empty_title() -> None:
    assert tg._parse_task_command("/task\n") is None
    assert tg._parse_task_command("/task   ") is None


def test_parse_task_command_bot_name_variant() -> None:
    assert tg._parse_task_command("/task@mybot Do something") == ("Do something", None)


def test_parse_task_command_newline_only_title() -> None:
    result = tg._parse_task_command("/task Refactor module\n\nExtra notes")
    assert result is not None
    assert result[0] == "Refactor module"


# ---------------------------------------------------------------------------
# Offset persistence
# ---------------------------------------------------------------------------

def test_load_offset_missing_file(tmp_path: Path) -> None:
    assert tg._load_offset(tmp_path / "offset") is None


def test_save_and_load_offset(tmp_path: Path) -> None:
    path = tmp_path / "offset"
    tg._save_offset(path, 42)
    assert tg._load_offset(path) == 42


def test_save_offset_creates_parent_dirs(tmp_path: Path) -> None:
    path = tmp_path / "sub" / "dir" / "offset"
    tg._save_offset(path, 99)
    assert tg._load_offset(path) == 99


def test_load_offset_invalid_content(tmp_path: Path) -> None:
    path = tmp_path / "offset"
    path.write_text("not-a-number")
    assert tg._load_offset(path) is None


# ---------------------------------------------------------------------------
# inbound_listener — no token → exits immediately
# ---------------------------------------------------------------------------

def test_inbound_listener_exits_when_no_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    app = MagicMock()
    asyncio.run(tg.inbound_listener(app, tmp_path / "offset"))
    # Must return without making any calls
    app.state.fleet_state.config  # not accessed


# ---------------------------------------------------------------------------
# inbound_listener — empty allowlist → no polling
# ---------------------------------------------------------------------------

def test_inbound_listener_skips_polling_when_allowlist_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")

    cfg = RuntimeConfig(telegram_allowed_ids="")
    app = MagicMock()
    app.state.fleet_state.config = cfg

    fetched: list = []

    async def _fake_to_thread(fn, *args):
        fetched.append(fn)
        raise asyncio.CancelledError()

    call_n = [0]

    async def _fake_sleep(s: float) -> None:
        call_n[0] += 1
        if call_n[0] >= 2:
            raise asyncio.CancelledError()

    monkeypatch.setattr(asyncio, "sleep", _fake_sleep)
    monkeypatch.setattr(asyncio, "to_thread", _fake_to_thread)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(tg.inbound_listener(app, tmp_path / "offset"))

    assert fetched == [], "getUpdates must not be called when allowlist is empty"


# ---------------------------------------------------------------------------
# inbound_listener — rejected sender
# ---------------------------------------------------------------------------

def test_inbound_listener_rejects_unknown_sender(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")

    cfg = RuntimeConfig(telegram_allowed_ids="999")  # only 999 is allowed
    app = MagicMock()
    app.state.fleet_state.config = cfg

    updates = [{"update_id": 10, "message": {"from": {"id": 111}, "chat": {"id": 111}, "text": "/task Bad actor"}}]

    call_n = [0]

    async def _fake_to_thread(fn, *args):
        call_n[0] += 1
        if call_n[0] == 1:
            return updates  # _fetch_updates
        raise asyncio.CancelledError()

    async def _fake_send(token, chat_id, text):
        raise AssertionError("send_message must not be called for rejected sender")

    monkeypatch.setattr(asyncio, "to_thread", _fake_to_thread)
    monkeypatch.setattr(tg, "send_message", _fake_send)

    with pytest.raises((asyncio.CancelledError, StopAsyncIteration)):
        asyncio.run(tg.inbound_listener(app, tmp_path / "offset"))

    # Offset should have advanced past the rejected update
    assert tg._load_offset(tmp_path / "offset") == 11


# ---------------------------------------------------------------------------
# inbound_listener — creates task on /task command
# ---------------------------------------------------------------------------

def test_inbound_listener_creates_task_and_replies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")

    cfg = RuntimeConfig(telegram_allowed_ids="123", telegram_default_cwd="/my/project")
    app = MagicMock()
    app.state.fleet_state.config = cfg

    from fleet.schemas import Task
    fake_task = Task(id="fleet-abc1", title="Fix the bug", description=None, status="open")
    app.state.queue.create_task.return_value = fake_task

    updates = [{"update_id": 5, "message": {"from": {"id": 123}, "chat": {"id": 123}, "text": "/task Fix the bug\nSome details"}}]

    sent: list[tuple[str, str]] = []  # (chat_id, text)

    async def _fake_send(token, chat_id, text):
        sent.append((chat_id, text))

    call_n = [0]

    async def _fake_to_thread(fn, *args):
        call_n[0] += 1
        if call_n[0] == 1:
            return updates  # _fetch_updates
        if call_n[0] == 2:
            # create_task call via to_thread
            return fn(*args)
        raise asyncio.CancelledError()

    monkeypatch.setattr(asyncio, "to_thread", _fake_to_thread)
    monkeypatch.setattr(tg, "send_message", _fake_send)

    with pytest.raises((asyncio.CancelledError, StopAsyncIteration)):
        asyncio.run(tg.inbound_listener(app, tmp_path / "offset"))

    assert len(sent) == 1
    assert "fleet-abc1" in sent[0][1]
    assert tg._load_offset(tmp_path / "offset") == 6


# ---------------------------------------------------------------------------
# inbound_listener — error backoff
# ---------------------------------------------------------------------------

def test_inbound_listener_backs_off_on_network_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")

    cfg = RuntimeConfig(telegram_allowed_ids="123")
    app = MagicMock()
    app.state.fleet_state.config = cfg

    call_n = [0]
    sleep_durations: list[float] = []

    async def _fake_to_thread(fn, *args):
        call_n[0] += 1
        if call_n[0] <= 2:
            raise OSError("network failure")
        raise asyncio.CancelledError()

    async def _fake_sleep(s: float) -> None:
        sleep_durations.append(s)

    monkeypatch.setattr(asyncio, "to_thread", _fake_to_thread)
    monkeypatch.setattr(asyncio, "sleep", _fake_sleep)

    with pytest.raises((asyncio.CancelledError, StopAsyncIteration)):
        asyncio.run(tg.inbound_listener(app, tmp_path / "offset"))

    assert len(sleep_durations) >= 2
    # Backoff doubles: second sleep should be >= first
    assert sleep_durations[1] >= sleep_durations[0]
