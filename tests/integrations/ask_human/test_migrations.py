"""Schema versioning for the ask_human store (ADR 0006 bead 24).

The store stamps its schema level in ``PRAGMA user_version`` and applies
``MIGRATIONS`` in order: fresh databases land at the latest version, old
ones migrate up, and a database stamped ahead of its columns (a
half-applied schema) is repaired instead of silently obeyed.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from fleet.integrations.ask_human.store import MIGRATIONS, SCHEMA_VERSION, QuestionStore


def _user_version(path: Path) -> int:
    conn = sqlite3.connect(path)
    try:
        return int(conn.execute("PRAGMA user_version").fetchone()[0])
    finally:
        conn.close()


def _columns(path: Path) -> set[str]:
    conn = sqlite3.connect(path)
    try:
        return {row[1] for row in conn.execute("PRAGMA table_info(questions)")}
    finally:
        conn.close()


def test_fresh_db_lands_at_latest_version(tmp_path: Path):
    path = tmp_path / "fresh.db"
    QuestionStore(path)
    assert _user_version(path) == SCHEMA_VERSION == len(MIGRATIONS)
    assert {"note", "task_id", "context"} <= _columns(path)


def test_v0_db_migrates_with_rows_intact(tmp_path: Path):
    # A database from before note/task_id/context existed (version 0).
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        "CREATE TABLE questions (id TEXT PRIMARY KEY, agent_id TEXT, session_id TEXT, "
        "prompt TEXT NOT NULL, options TEXT, multi_select INTEGER NOT NULL DEFAULT 0, "
        "priority INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'pending', "
        "answer TEXT, default_answer TEXT, timeout_s REAL, answered_by TEXT, "
        "created_at REAL NOT NULL, answered_at REAL);"
    )
    conn.execute(
        "INSERT INTO questions (id, prompt, status, created_at) VALUES "
        "('old1', 'legacy row', 'pending', 1.0)"
    )
    conn.commit()
    conn.close()

    store = QuestionStore(path)  # opening migrates
    assert _user_version(path) == SCHEMA_VERSION
    assert store.get("old1")["prompt"] == "legacy row"
    assert store.answer("old1", "yes", note="works after migrate")
    assert store.get("old1")["note"] == "works after migrate"


def test_partial_schema_is_detected_and_repaired(tmp_path: Path):
    # Half-applied schema: the version stamp claims everything is done,
    # but the `context` column never landed.
    path = tmp_path / "partial.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        "CREATE TABLE questions (id TEXT PRIMARY KEY, agent_id TEXT, session_id TEXT, "
        "prompt TEXT NOT NULL, options TEXT, multi_select INTEGER NOT NULL DEFAULT 0, "
        "priority INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'pending', "
        "answer TEXT, note TEXT, task_id TEXT, default_answer TEXT, timeout_s REAL, "
        "answered_by TEXT, created_at REAL NOT NULL, answered_at REAL);"
    )
    conn.execute(
        "INSERT INTO questions (id, prompt, status, created_at) VALUES "
        "('half1', 'half-migrated row', 'pending', 2.0)"
    )
    conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
    conn.commit()
    conn.close()

    store = QuestionStore(path)  # opening must repair, not trust the stamp
    assert "context" in _columns(path)
    assert _user_version(path) == SCHEMA_VERSION
    assert store.get("half1")["prompt"] == "half-migrated row"
