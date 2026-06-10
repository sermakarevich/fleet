"""Correctness checks for the vendored ask_human QuestionStore.

Adapted from the upstream agent-chat test suite (~/git/claude/mcp/ask_human).
Covers the properties the whole design rests on: a blocking ask that is
answered out-of-band, timeout -> default, first-writer-wins, and many
concurrent waiters being released independently.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

from fleet.ask_human.store import QuestionStore


def _store(tmp_path: Path) -> QuestionStore:
    return QuestionStore(tmp_path / "q.db")


def test_blocking_ask_answered_out_of_band(tmp_path: Path):
    s = _store(tmp_path)
    qid = s.create("Deploy to prod?", options=["yes", "no"], agent_id="agent-7")

    def operator():
        time.sleep(0.3)
        assert s.answer(qid, "yes", answered_by="cli")

    t = threading.Thread(target=operator)
    t.start()
    q = s.wait(qid, poll_interval=0.05)  # blocks until the operator answers
    t.join()

    assert q["status"] == "answered"
    assert q["answer"] == "yes"
    assert q["answered_by"] == "cli"


def test_timeout_returns_default(tmp_path: Path):
    s = _store(tmp_path)
    qid = s.create("Proceed?", timeout_s=0.2, default_answer="no")
    q = s.wait(qid, poll_interval=0.05)
    assert q["status"] == "expired"
    assert q["answer"] == "no"


def test_first_writer_wins(tmp_path: Path):
    s = _store(tmp_path)
    qid = s.create("Pick one")
    assert s.answer(qid, "a") is True
    assert s.answer(qid, "b") is False          # already resolved
    assert s.get(qid)["answer"] == "a"


def test_many_concurrent_waiters_released_independently(tmp_path: Path):
    s = _store(tmp_path)
    ids = [s.create(f"q{i}") for i in range(20)]
    results: dict[str, dict] = {}

    def wait_one(qid: str):
        results[qid] = s.wait(qid, poll_interval=0.02)

    threads = [threading.Thread(target=wait_one, args=(i,)) for i in ids]
    for t in threads:
        t.start()
    time.sleep(0.1)
    for i in ids:
        assert s.answer(i, f"ans-{i}")
    for t in threads:
        t.join()

    assert all(results[i]["status"] == "answered" for i in ids)
    assert all(results[i]["answer"] == f"ans-{i}" for i in ids)


def test_multi_select_and_listing(tmp_path: Path):
    s = _store(tmp_path)
    qid = s.create("Languages?", options=["py", "ts", "go"], multi_select=True)
    assert any(p["id"] == qid for p in s.list_pending())
    s.answer(qid, ["py", "go"])
    assert s.get(qid)["answer"] == ["py", "go"]


def test_answer_with_note_supplements_selection(tmp_path: Path):
    s = _store(tmp_path)
    qid = s.create("Deploy to prod?", options=["yes", "no"])
    assert s.answer(qid, "yes", note="but wait for the migration to finish")
    q = s.get(qid)
    assert q["answer"] == "yes"
    assert q["note"] == "but wait for the migration to finish"


def test_note_only_answer_overrides_options(tmp_path: Path):
    # The operator picks nothing because none of the options fit, answering purely
    # in free text. `answer` stays None; the real reply lives in `note`.
    s = _store(tmp_path)
    qid = s.create("Which DB?", options=["postgres", "mysql"])
    assert s.answer(qid, None, note="actually use sqlite")
    q = s.get(qid)
    assert q["answer"] is None
    assert q["note"] == "actually use sqlite"


def test_migration_adds_note_column_to_preexisting_db(tmp_path: Path):
    # A DB created before `note` existed must gain the column on open (and keep
    # its rows) — the live questions.db is exactly this case.
    import sqlite3

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

    s = QuestionStore(path)  # opening runs the migration
    assert s.get("old1")["note"] is None            # pre-existing row survives
    assert s.answer("old1", "yes", note="works after migrate")
    assert s.get("old1")["note"] == "works after migrate"


def test_resolve_id_prefix_and_cancel(tmp_path: Path):
    s = _store(tmp_path)
    qid = s.create("cancel me")
    assert s.resolve_id(qid[:6]) == qid
    assert s.cancel(qid) is True
    assert s.answer(qid, "late") is False       # can't answer a cancelled one


def test_shared_db_with_fleet_ask_human_db_helpers(tmp_path: Path):
    # The vendored store and fleet.ask_human_db are two clients of the same
    # SQLite file; an answer written through either side must be visible to the
    # other (this is exactly the serve-process / MCP-server split in production).
    import fleet.ask_human_db as ahdb

    path = tmp_path / "q.db"
    s = QuestionStore(path)
    qid = s.create("Cross-module?", options=["a", "b"], agent_id="x")

    pending = ahdb.fetch_pending_questions(db_path=path)
    assert [p["id"] for p in pending] == [qid]

    result = ahdb.answer_question(qid, "a", "web", db_path=path)
    assert result["ok"] is True
    q = s.get(qid)
    assert q["status"] == "answered"
    assert q["answer"] == "a"
    assert q["answered_by"] == "web"
