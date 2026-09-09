"""Shared scaffolding for telegram integration tests.

Called by ``test_notifier_*.py`` and ``test_bot_*.py``: hand-rolled question
rows, a fake serve app with an explicit token, listener parts wired to an
injected ``FakeTelegramApi``, and a scripted sleep that drives poll loops
without patching ``asyncio``.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from fleet.core.config import RuntimeConfig
from fleet.integrations.ask_human.store import QuestionStore
from fleet.integrations.telegram.api import TelegramApi
from fleet.integrations.telegram.commands import CommandEnv, parse_allowed_ids
from fleet.integrations.telegram.listener import inbound_listener
from fleet.integrations.telegram.messages import MessageStore, OffsetStore
from tests.helpers.fakes import FakeTelegramApi

QUESTION_COLUMNS = (
    "id TEXT PRIMARY KEY, agent_id TEXT, session_id TEXT, prompt TEXT, "
    "options TEXT, multi_select INTEGER DEFAULT 0, priority INTEGER DEFAULT 0, "
    "created_at REAL, timeout_s REAL, default_answer TEXT, "
    "status TEXT DEFAULT 'pending', answer TEXT, note TEXT, "
    "answered_by TEXT, answered_at REAL"
)


def create_questions_db(path: Path) -> None:
    """Create a question table with the columns the poller tests insert."""
    conn = sqlite3.connect(str(path))
    conn.execute(f"CREATE TABLE questions ({QUESTION_COLUMNS})")
    conn.commit()
    conn.close()


def insert_question(
    path: Path,
    *,
    qid: str,
    prompt: str,
    created_at: float,
    status: str = "pending",
    options: list[str] | None = None,
    agent_id: str = "test-agent",
    answer: str | None = None,
) -> None:
    """Insert one pending question row a test can then poll for."""
    conn = sqlite3.connect(str(path))
    conn.execute(
        "INSERT INTO questions (id, agent_id, prompt, created_at, status, options, answer)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (qid, agent_id, prompt, created_at, status, json.dumps(options), answer),
    )
    conn.commit()
    conn.close()


def make_fake_app(
    chat_id: str = "999",
    store: QuestionStore | None = None,
    fleet_home: Path | None = None,
    token: str = "tok",
    allowed_ids: str = "",
) -> MagicMock:
    """A serve app double with an explicit token (no env reads, no patching)."""
    config = RuntimeConfig(telegram_chat_id=chat_id, telegram_allowed_ids=allowed_ids)
    fake_app = MagicMock()
    fake_app.state.fleet_state.config = config
    fake_app.state.fleet_state.question_store = store
    fake_app.state.fleet_state.fleet_home = fleet_home
    fake_app.state.fleet_state.telegram_token = token
    return fake_app


def listener_parts(
    app: MagicMock,
    tmp_path: Path,
    *,
    api: TelegramApi | None = None,
    qmsgs: str = "qmsgs.json",
    db: Path | None = None,
) -> tuple[TelegramApi, QuestionStore, CommandEnv, OffsetStore]:
    """Build (api, store, env, offsets) for inbound_listener from the fake app."""
    config = app.state.fleet_state.config
    return (
        api if api is not None else TelegramApi("tok"),
        QuestionStore(db or tmp_path / "questions.db"),
        CommandEnv(
            queue=app.state.queue,
            messages=MessageStore(tmp_path / qmsgs),
            allowed_ids=lambda: parse_allowed_ids(config.telegram_allowed_ids),
            default_cwd=lambda: config.telegram_default_cwd or None,
        ),
        OffsetStore(tmp_path / "offset"),
    )


def run_listener(
    app: MagicMock,
    tmp_path: Path,
    *,
    api: TelegramApi | None = None,
    sleep_fn: Any = None,
) -> None:
    """Build listener parts from the fake app and drive until CancelledError."""
    api_arg, store, env, offsets = listener_parts(app, tmp_path, api=api)
    return asyncio.run(inbound_listener(api_arg, store, env, offsets, sleep_fn=sleep_fn))


def scripted_updates(page: list[dict]) -> FakeTelegramApi:
    """A fake api that serves one updates page, then ends the loop cleanly."""
    return FakeTelegramApi("tok", updates=[page, asyncio.CancelledError()])


class SleepScript:
    """A scripted sleep_fn: records pauses, runs per-call hooks, then stops.

    Poll-loop tests pass it as ``sleep_fn``/``sleep`` instead of patching
    ``asyncio.sleep``: ``hooks`` maps a 1-based call number to a callable
    (e.g. insert a question after the watermark is set); the ``stop_after``
    call raises ``CancelledError`` to end the loop under test, or never
    when ``stop_after`` is None (the loop ends another way).
    """

    def __init__(self, stop_after: int | None, hooks: dict[int, Any] | None = None) -> None:
        self.stop_after = stop_after
        self.hooks = dict(hooks or {})
        self.calls: list[float] = []

    async def __call__(self, delay: float) -> None:
        """Record one pause, run its hook, stop the loop at the last call."""
        self.calls.append(delay)
        hook = self.hooks.get(len(self.calls))
        if hook is not None:
            hook()
        if self.stop_after is not None and len(self.calls) >= self.stop_after:
            raise asyncio.CancelledError()
