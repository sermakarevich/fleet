"""Triage-facing QuestionStore methods: ask/fetch_pending_for_task/fetch_answered_triage."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from fleet.integrations.ask_human.store import QuestionStore


def _store(tmp_path: Path) -> QuestionStore:
    return QuestionStore(tmp_path / "q.db")


def test_ask_is_non_blocking_and_fetchable(tmp_path: Path):
    s = _store(tmp_path)
    qid = s.ask("fix t?", ["retry", "close"], task_id="t-1", context="blocked-at-1")
    assert qid
    rows = s.fetch_pending_for_task("t-1", "blocked-at-1")
    assert [r["id"] for r in rows] == [qid]
    assert rows[0]["options"] == ["retry", "close"]
    # Different context (re-blocked task) does not match.
    assert s.fetch_pending_for_task("t-1", "other") == []
    # No-context lookup matches any context.
    assert [r["id"] for r in s.fetch_pending_for_task("t-1")] == [qid]


def test_fetch_answered_triage_only_triage(tmp_path: Path):
    s = _store(tmp_path)
    q1 = s.ask("triage q?", ["a"], task_id="t-1", context="c")
    q2 = s.create("agent q?", agent_id="agent-7")
    s.answer(q1, "a", answered_by="op")
    s.answer(q2, "x", answered_by="op")
    rows = s.fetch_answered_triage()
    assert [r["id"] for r in rows] == [q1]


def test_migration_adds_columns_to_old_db(tmp_path: Path):

    db = tmp_path / "old.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE questions (id TEXT PRIMARY KEY, agent_id TEXT, session_id TEXT, "
        "prompt TEXT NOT NULL, options TEXT, multi_select INTEGER NOT NULL DEFAULT 0, "
        "priority INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'pending', "
        "answer TEXT, default_answer TEXT, timeout_s REAL, answered_by TEXT, "
        "created_at REAL NOT NULL, answered_at REAL)"
    )
    conn.execute(
        "INSERT INTO questions (id, prompt, status, created_at) "
        "VALUES ('q1', 'hi?', 'pending', 1.0)"
    )
    conn.commit()
    conn.close()
    s = QuestionStore(db)
    qid = s.ask("new?", ["a"], task_id="t", context="c")
    assert s.fetch_pending_for_task("t", "c")[0]["id"] == qid
