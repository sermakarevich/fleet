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

    async def _fake_send(token: str, chat_id: str, text: str) -> int | None:
        sent.append(text)
        return None

    monkeypatch.setattr(tg, "send_message_with_id", _fake_send)

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

    async def _failing_send(token: str, chat_id: str, text: str) -> int | None:
        raise RuntimeError("network boom")

    monkeypatch.setattr(tg, "send_message_with_id", _failing_send)

    call_n = [0]

    async def _fake_sleep(s: float) -> None:
        call_n[0] += 1
        if call_n[0] == 1:
            # Insert row so send_message_with_id is called (and raises)
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
    app.state.queue.create_task.assert_called_once_with(
        "Fix the bug", "Some details", None, None, "/my/project"
    )


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


# ---------------------------------------------------------------------------
# inbound_listener — malformed /task command gets error reply
# ---------------------------------------------------------------------------

def test_inbound_listener_malformed_task_sends_error_reply(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Malformed /task command (empty title) sends error reply; no task is created."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")

    cfg = RuntimeConfig(telegram_allowed_ids="123")
    app = MagicMock()
    app.state.fleet_state.config = cfg

    updates = [
        {
            "update_id": 20,
            "message": {
                "from": {"id": 123},
                "chat": {"id": 123},
                "text": "/task\n",  # empty title → malformed
            },
        }
    ]

    sent: list[tuple[str, str]] = []

    async def _fake_send(token: str, chat_id: str, text: str) -> None:
        sent.append((chat_id, text))

    call_n = [0]

    async def _fake_to_thread(fn, *args):
        call_n[0] += 1
        if call_n[0] == 1:
            return updates
        raise asyncio.CancelledError()

    monkeypatch.setattr(asyncio, "to_thread", _fake_to_thread)
    monkeypatch.setattr(tg, "send_message", _fake_send)

    with pytest.raises((asyncio.CancelledError, StopAsyncIteration)):
        asyncio.run(tg.inbound_listener(app, tmp_path / "offset"))

    app.state.queue.create_task.assert_not_called()
    assert len(sent) == 1, "Expected exactly one error reply"
    assert "usage" in sent[0][1].lower() or "Usage" in sent[0][1]
    assert tg._load_offset(tmp_path / "offset") == 21


# ---------------------------------------------------------------------------
# inbound_listener — offset persistence prevents duplicates on restart
# ---------------------------------------------------------------------------

def test_inbound_listener_offset_prevents_duplicate_on_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Saved offset from a previous run is passed to getUpdates on restart,
    preventing the same update from being processed twice."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")

    cfg = RuntimeConfig(telegram_allowed_ids="123", telegram_default_cwd="")

    updates = [
        {
            "update_id": 7,
            "message": {
                "from": {"id": 123},
                "chat": {"id": 123},
                "text": "/task Title",
            },
        }
    ]

    from fleet.schemas import Task

    fake_task = Task(id="fleet-xyz1", title="Title", description=None, status="open")
    offset_path = tmp_path / "offset"

    # --- First run: process the update and save offset ---
    app1 = MagicMock()
    app1.state.fleet_state.config = cfg
    app1.state.queue.create_task.return_value = fake_task

    async def _fake_send(token: str, chat_id: str, text: str) -> None:
        pass

    run1_n = [0]

    async def _fake_to_thread_run1(fn, *args):
        run1_n[0] += 1
        if run1_n[0] == 1:
            return updates
        if run1_n[0] == 2:
            return fn(*args)  # create_task
        raise asyncio.CancelledError()

    monkeypatch.setattr(asyncio, "to_thread", _fake_to_thread_run1)
    monkeypatch.setattr(tg, "send_message", _fake_send)

    with pytest.raises((asyncio.CancelledError, StopAsyncIteration)):
        asyncio.run(tg.inbound_listener(app1, offset_path))

    assert tg._load_offset(offset_path) == 8
    assert app1.state.queue.create_task.call_count == 1

    # --- Second run: offset=8 should be passed to _fetch_updates ---
    app2 = MagicMock()
    app2.state.fleet_state.config = cfg

    fetched_offsets: list = []
    run2_n = [0]

    async def _fake_to_thread_run2(fn, *args):
        run2_n[0] += 1
        if run2_n[0] == 1:
            fetched_offsets.append(args[1])  # args = (token, offset)
            return []  # no new updates (Telegram filters out update_id < offset)
        raise asyncio.CancelledError()

    monkeypatch.setattr(asyncio, "to_thread", _fake_to_thread_run2)

    with pytest.raises((asyncio.CancelledError, StopAsyncIteration)):
        asyncio.run(tg.inbound_listener(app2, offset_path))

    assert fetched_offsets == [8], "Second run must use saved offset=8"
    app2.state.queue.create_task.assert_not_called()


# ---------------------------------------------------------------------------
# send_message_with_id
# ---------------------------------------------------------------------------

class _JsonResp:
    def __init__(self, body: dict) -> None:
        self._data = json.dumps(body).encode()

    def read(self) -> bytes:
        return self._data

    def __enter__(self) -> "_JsonResp":
        return self

    def __exit__(self, *a: object) -> None:
        pass


def test_send_message_with_id_returns_message_id(monkeypatch: pytest.MonkeyPatch) -> None:
    """Returns message_id int on a successful Telegram response."""
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda req, timeout=None: _JsonResp({"ok": True, "result": {"message_id": 42}}),
    )
    result = asyncio.run(tg.send_message_with_id("tok", "123", "hello"))
    assert result == 42


def test_send_message_with_id_returns_none_on_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Returns None when the HTTP call fails."""
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda req, timeout=None: (_ for _ in ()).throw(OSError("refused")),
    )
    assert asyncio.run(tg.send_message_with_id("tok", "123", "hi")) is None


def test_send_message_with_id_returns_none_when_ok_false(monkeypatch: pytest.MonkeyPatch) -> None:
    """Returns None when Telegram responds ok=false."""
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda req, timeout=None: _JsonResp({"ok": False, "description": "Bad Request"}),
    )
    assert asyncio.run(tg.send_message_with_id("tok", "123", "hi")) is None


def test_send_message_with_id_truncates_to_4096(monkeypatch: pytest.MonkeyPatch) -> None:
    """Text is truncated to 4096 chars before sending."""
    lengths: list[int] = []

    def _fake_urlopen(req, timeout=None):
        lengths.append(len(json.loads(req.data.decode())["text"]))
        return _JsonResp({"ok": True, "result": {"message_id": 1}})

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)
    asyncio.run(tg.send_message_with_id("tok", "cid", "x" * 5000))
    assert lengths == [4096]


# ---------------------------------------------------------------------------
# record_question_message / lookup_question_for_message
# ---------------------------------------------------------------------------

def test_record_and_lookup_question_message(tmp_path: Path) -> None:
    """Basic round-trip: record then look up."""
    path = tmp_path / "q_msgs.json"
    tg.record_question_message(path, 100, "q-abc")
    assert tg.lookup_question_for_message(path, 100) == "q-abc"
    assert tg.lookup_question_for_message(path, 999) is None


def test_lookup_question_for_message_missing_file(tmp_path: Path) -> None:
    """lookup returns None when the mapping file does not exist."""
    assert tg.lookup_question_for_message(tmp_path / "missing.json", 1) is None


def test_record_question_message_caps_at_200(tmp_path: Path) -> None:
    """Oldest entries are evicted when the mapping exceeds 200 entries."""
    path = tmp_path / "q_msgs.json"
    for i in range(205):
        tg.record_question_message(path, i, f"q-{i}")
    mapping = json.loads(path.read_text())
    assert len(mapping) == 200
    # Oldest 5 entries evicted
    for i in range(5):
        assert str(i) not in mapping
    assert "5" in mapping
    assert "204" in mapping


def test_record_question_message_overwrites_existing_key(tmp_path: Path) -> None:
    """Recording the same message_id twice updates the value."""
    path = tmp_path / "q_msgs.json"
    tg.record_question_message(path, 1, "q-first")
    tg.record_question_message(path, 1, "q-second")
    assert tg.lookup_question_for_message(path, 1) == "q-second"


def test_record_question_message_swallows_oserror(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """OSError during write is swallowed; function must not raise."""
    import pathlib

    def _bad_write(self: Path, data: str, encoding: str | None = None, **kw: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(pathlib.Path, "write_text", _bad_write)
    # Must not raise
    tg.record_question_message(tmp_path / "q_msgs.json", 1, "q-1")


# ---------------------------------------------------------------------------
# Poller records message_id -> question_id mapping
# ---------------------------------------------------------------------------

def test_poller_records_message_id_mapping(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When send_message_with_id returns a message_id the poller persists the mapping."""
    db_path = tmp_path / "questions.db"
    _create_questions_db(db_path)
    _insert_question(db_path, qid="q-pre", prompt="pre-existing", created_at=1000.0)

    import fleet.serve.app as app_mod
    import fleet.serve.routes.chat as chat_mod

    monkeypatch.setattr(app_mod, "ASK_HUMAN_DB", db_path)
    monkeypatch.setattr(chat_mod, "ASK_HUMAN_DB", db_path)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")

    sent: list[str] = []

    async def _fake_send_with_id(token: str, chat_id: str, text: str) -> int | None:
        sent.append(text)
        return 777

    monkeypatch.setattr(tg, "send_message_with_id", _fake_send_with_id)

    cfg = RuntimeConfig(telegram_chat_id="999")
    fake_app = MagicMock()
    fake_app.state.fleet_state.config = cfg
    fake_app.state.fleet_state.fleet_home = tmp_path

    call_n = [0]

    async def _fake_sleep(s: float) -> None:
        call_n[0] += 1
        if call_n[0] == 1:
            _insert_question(db_path, qid="q-new", prompt="ask me?", created_at=2000.0)
        elif call_n[0] >= 3:
            raise asyncio.CancelledError()

    monkeypatch.setattr(asyncio, "sleep", _fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(app_mod._question_poller(fake_app))

    assert len(sent) == 1
    assert "ask me?" in sent[0]
    mapping_path = tmp_path / "telegram_question_msgs.json"
    assert mapping_path.exists()
    mapping = json.loads(mapping_path.read_text())
    assert mapping.get("777") == "q-new"


# ---------------------------------------------------------------------------
# inbound_listener — answer via reply-to / single-pending / option shortcut
# ---------------------------------------------------------------------------

def _make_fetch_dispatcher(updates: list) -> object:
    """Fake asyncio.to_thread: returns updates on 1st _fetch_updates call,
    CancelledError on 2nd; calls fn(*args) for all other functions."""
    fetch_n = [0]

    async def _fake(fn, *args):  # type: ignore[misc]
        if fn is tg._fetch_updates:
            fetch_n[0] += 1
            if fetch_n[0] == 1:
                return updates
            raise asyncio.CancelledError()
        return fn(*args)

    return _fake


def test_inbound_listener_answer_via_reply_to(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Replying to a question message resolves it and replies 'Answered [agent_id]'."""
    import fleet.ask_human_db as db_mod

    db_path = tmp_path / "questions.db"
    _create_questions_db(db_path)
    _insert_question(db_path, qid="q-reply", prompt="color?", created_at=1000.0)
    monkeypatch.setattr(db_mod, "ASK_HUMAN_DB", db_path)

    qmsg_path = tmp_path / "qmsgs.json"
    tg.record_question_message(qmsg_path, 42, "q-reply")

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    cfg = RuntimeConfig(telegram_allowed_ids="123")
    app = MagicMock()
    app.state.fleet_state.config = cfg

    updates = [{
        "update_id": 5,
        "message": {
            "from": {"id": 123},
            "chat": {"id": 123},
            "text": "blue",
            "reply_to_message": {"message_id": 42},
        },
    }]

    sent: list[tuple[str, str]] = []

    async def _fake_send(token: str, chat_id: str, text: str) -> None:
        sent.append((chat_id, text))

    monkeypatch.setattr(asyncio, "to_thread", _make_fetch_dispatcher(updates))
    monkeypatch.setattr(tg, "send_message", _fake_send)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(tg.inbound_listener(app, tmp_path / "offset", qmsg_path))

    assert len(sent) == 1
    assert "Answered" in sent[0][1]
    assert "test-agent" in sent[0][1] or "q-reply" in sent[0][1]

    conn = sqlite3.connect(str(db_path))
    row = conn.execute("SELECT status, answer FROM questions WHERE id='q-reply'").fetchone()
    conn.close()
    assert row[0] == "answered"
    assert json.loads(row[1]) == "blue"
    assert tg._load_offset(tmp_path / "offset") == 6


def test_inbound_listener_reply_to_unknown_mapping(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reply-to a message not in the mapping replies 'Unknown or expired question'."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    cfg = RuntimeConfig(telegram_allowed_ids="123")
    app = MagicMock()
    app.state.fleet_state.config = cfg

    updates = [{
        "update_id": 6,
        "message": {
            "from": {"id": 123},
            "chat": {"id": 123},
            "text": "some answer",
            "reply_to_message": {"message_id": 999},
        },
    }]

    sent: list[tuple[str, str]] = []

    async def _fake_send(token: str, chat_id: str, text: str) -> None:
        sent.append((chat_id, text))

    monkeypatch.setattr(asyncio, "to_thread", _make_fetch_dispatcher(updates))
    monkeypatch.setattr(tg, "send_message", _fake_send)

    qmsg_path = tmp_path / "qmsgs.json"  # empty / non-existent mapping

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(tg.inbound_listener(app, tmp_path / "offset", qmsg_path))

    assert len(sent) == 1
    assert sent[0][1] == "Unknown or expired question"


def test_inbound_listener_reply_to_already_answered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reply-to an already-answered question replies 'Question already answered'."""
    import fleet.ask_human_db as db_mod

    db_path = tmp_path / "questions.db"
    _create_questions_db(db_path)
    _insert_question(db_path, qid="q-done", prompt="done?", created_at=1000.0, status="answered")
    monkeypatch.setattr(db_mod, "ASK_HUMAN_DB", db_path)

    qmsg_path = tmp_path / "qmsgs.json"
    tg.record_question_message(qmsg_path, 77, "q-done")

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    cfg = RuntimeConfig(telegram_allowed_ids="123")
    app = MagicMock()
    app.state.fleet_state.config = cfg

    updates = [{
        "update_id": 7,
        "message": {
            "from": {"id": 123},
            "chat": {"id": 123},
            "text": "too late",
            "reply_to_message": {"message_id": 77},
        },
    }]

    sent: list[tuple[str, str]] = []

    async def _fake_send(token: str, chat_id: str, text: str) -> None:
        sent.append((chat_id, text))

    monkeypatch.setattr(asyncio, "to_thread", _make_fetch_dispatcher(updates))
    monkeypatch.setattr(tg, "send_message", _fake_send)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(tg.inbound_listener(app, tmp_path / "offset", qmsg_path))

    assert len(sent) == 1
    assert sent[0][1] == "Question already answered"


def test_inbound_listener_single_pending_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Plain text with exactly one pending question answers it via fallback."""
    import fleet.ask_human_db as db_mod

    db_path = tmp_path / "questions.db"
    _create_questions_db(db_path)
    _insert_question(db_path, qid="q-one", prompt="scale?", created_at=1000.0)
    monkeypatch.setattr(db_mod, "ASK_HUMAN_DB", db_path)

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    cfg = RuntimeConfig(telegram_allowed_ids="123")
    app = MagicMock()
    app.state.fleet_state.config = cfg

    updates = [{
        "update_id": 8,
        "message": {
            "from": {"id": 123},
            "chat": {"id": 123},
            "text": "fine thanks",
        },
    }]

    sent: list[tuple[str, str]] = []

    async def _fake_send(token: str, chat_id: str, text: str) -> None:
        sent.append((chat_id, text))

    monkeypatch.setattr(asyncio, "to_thread", _make_fetch_dispatcher(updates))
    monkeypatch.setattr(tg, "send_message", _fake_send)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(tg.inbound_listener(app, tmp_path / "offset", tmp_path / "qmsgs.json"))

    assert len(sent) == 1
    assert "Answered" in sent[0][1]

    conn = sqlite3.connect(str(db_path))
    row = conn.execute("SELECT status, answer FROM questions WHERE id='q-one'").fetchone()
    conn.close()
    assert row[0] == "answered"
    assert json.loads(row[1]) == "fine thanks"


def test_inbound_listener_multiple_pending_reply(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Plain text with multiple pending questions sends a count hint."""
    import fleet.ask_human_db as db_mod

    db_path = tmp_path / "questions.db"
    _create_questions_db(db_path)
    _insert_question(db_path, qid="q-a", prompt="first?", created_at=1000.0)
    _insert_question(db_path, qid="q-b", prompt="second?", created_at=1001.0)
    monkeypatch.setattr(db_mod, "ASK_HUMAN_DB", db_path)

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    cfg = RuntimeConfig(telegram_allowed_ids="123")
    app = MagicMock()
    app.state.fleet_state.config = cfg

    updates = [{
        "update_id": 9,
        "message": {
            "from": {"id": 123},
            "chat": {"id": 123},
            "text": "hello",
        },
    }]

    sent: list[tuple[str, str]] = []

    async def _fake_send(token: str, chat_id: str, text: str) -> None:
        sent.append((chat_id, text))

    monkeypatch.setattr(asyncio, "to_thread", _make_fetch_dispatcher(updates))
    monkeypatch.setattr(tg, "send_message", _fake_send)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(tg.inbound_listener(app, tmp_path / "offset", tmp_path / "qmsgs.json"))

    assert len(sent) == 1
    assert "2 questions pending" in sent[0][1]
    assert "reply directly" in sent[0][1]


def test_inbound_listener_zero_pending_silently_dropped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Plain text with no pending questions is silently dropped."""
    import fleet.ask_human_db as db_mod

    db_path = tmp_path / "questions.db"
    _create_questions_db(db_path)
    monkeypatch.setattr(db_mod, "ASK_HUMAN_DB", db_path)

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    cfg = RuntimeConfig(telegram_allowed_ids="123")
    app = MagicMock()
    app.state.fleet_state.config = cfg

    updates = [{
        "update_id": 10,
        "message": {
            "from": {"id": 123},
            "chat": {"id": 123},
            "text": "just chatting",
        },
    }]

    sent: list[tuple[str, str]] = []

    async def _fake_send(token: str, chat_id: str, text: str) -> None:
        sent.append((chat_id, text))

    monkeypatch.setattr(asyncio, "to_thread", _make_fetch_dispatcher(updates))
    monkeypatch.setattr(tg, "send_message", _fake_send)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(tg.inbound_listener(app, tmp_path / "offset", tmp_path / "qmsgs.json"))

    assert sent == [], "No reply sent when there are no pending questions"


def test_inbound_listener_numeric_option_shortcut(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bare integer text picks the matching option string from the question's options list."""
    import fleet.ask_human_db as db_mod

    db_path = tmp_path / "questions.db"
    _create_questions_db(db_path)
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT INTO questions (id, agent_id, prompt, created_at, status, options) "
        "VALUES (?, ?, ?, ?, 'pending', ?)",
        ("q-opt", "agent-opts", "pick one?", 1000.0, json.dumps(["alpha", "beta", "gamma"])),
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(db_mod, "ASK_HUMAN_DB", db_path)

    qmsg_path = tmp_path / "qmsgs.json"
    tg.record_question_message(qmsg_path, 55, "q-opt")

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    cfg = RuntimeConfig(telegram_allowed_ids="123")
    app = MagicMock()
    app.state.fleet_state.config = cfg

    updates = [{
        "update_id": 11,
        "message": {
            "from": {"id": 123},
            "chat": {"id": 123},
            "text": "2",
            "reply_to_message": {"message_id": 55},
        },
    }]

    sent: list[tuple[str, str]] = []

    async def _fake_send(token: str, chat_id: str, text: str) -> None:
        sent.append((chat_id, text))

    monkeypatch.setattr(asyncio, "to_thread", _make_fetch_dispatcher(updates))
    monkeypatch.setattr(tg, "send_message", _fake_send)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(tg.inbound_listener(app, tmp_path / "offset", qmsg_path))

    assert len(sent) == 1
    assert "Answered" in sent[0][1]
    assert "agent-opts" in sent[0][1]

    conn = sqlite3.connect(str(db_path))
    row = conn.execute("SELECT answer FROM questions WHERE id='q-opt'").fetchone()
    conn.close()
    assert json.loads(row[0]) == "beta"


def test_inbound_listener_numeric_out_of_range_stored_as_string(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Integer text out of options range is stored as the raw string, not an option."""
    import fleet.ask_human_db as db_mod

    db_path = tmp_path / "questions.db"
    _create_questions_db(db_path)
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT INTO questions (id, agent_id, prompt, created_at, status, options) "
        "VALUES (?, ?, ?, ?, 'pending', ?)",
        ("q-out", "agent-out", "pick?", 1000.0, json.dumps(["x", "y"])),
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(db_mod, "ASK_HUMAN_DB", db_path)

    qmsg_path = tmp_path / "qmsgs.json"
    tg.record_question_message(qmsg_path, 88, "q-out")

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    cfg = RuntimeConfig(telegram_allowed_ids="123")
    app = MagicMock()
    app.state.fleet_state.config = cfg

    updates = [{
        "update_id": 12,
        "message": {
            "from": {"id": 123},
            "chat": {"id": 123},
            "text": "99",
            "reply_to_message": {"message_id": 88},
        },
    }]

    sent: list[tuple[str, str]] = []

    async def _fake_send(token: str, chat_id: str, text: str) -> None:
        sent.append((chat_id, text))

    monkeypatch.setattr(asyncio, "to_thread", _make_fetch_dispatcher(updates))
    monkeypatch.setattr(tg, "send_message", _fake_send)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(tg.inbound_listener(app, tmp_path / "offset", qmsg_path))

    assert len(sent) == 1
    assert "Answered" in sent[0][1]

    conn = sqlite3.connect(str(db_path))
    row = conn.execute("SELECT answer FROM questions WHERE id='q-out'").fetchone()
    conn.close()
    assert json.loads(row[0]) == "99"  # stored as raw string, not option


def test_inbound_listener_slash_command_not_intercepted_by_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Commands like /start are silently dropped and do not trigger the answer fallback."""
    import fleet.ask_human_db as db_mod

    db_path = tmp_path / "questions.db"
    _create_questions_db(db_path)
    _insert_question(db_path, qid="q-cmd", prompt="pending?", created_at=1000.0)
    monkeypatch.setattr(db_mod, "ASK_HUMAN_DB", db_path)

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    cfg = RuntimeConfig(telegram_allowed_ids="123")
    app = MagicMock()
    app.state.fleet_state.config = cfg

    updates = [{
        "update_id": 13,
        "message": {
            "from": {"id": 123},
            "chat": {"id": 123},
            "text": "/start",
        },
    }]

    sent: list[tuple[str, str]] = []

    async def _fake_send(token: str, chat_id: str, text: str) -> None:
        sent.append((chat_id, text))

    monkeypatch.setattr(asyncio, "to_thread", _make_fetch_dispatcher(updates))
    monkeypatch.setattr(tg, "send_message", _fake_send)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(tg.inbound_listener(app, tmp_path / "offset", tmp_path / "qmsgs.json"))

    assert sent == [], "/start must be silently dropped, not treated as an answer"

    conn = sqlite3.connect(str(db_path))
    row = conn.execute("SELECT status FROM questions WHERE id='q-cmd'").fetchone()
    conn.close()
    assert row[0] == "pending", "Question must remain pending"
