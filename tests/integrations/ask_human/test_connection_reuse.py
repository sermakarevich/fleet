"""One SQLite connection per thread (ADR 0006 bead 24).

The store opens a single connection per thread (PRAGMAs set once) instead
of a new connection per operation: the same thread always sees the same
connection, different threads never share one, and writes from one thread
are visible to the others.
"""

from __future__ import annotations

import threading
from pathlib import Path

from fleet.integrations.ask_human.store import QuestionStore


def test_same_thread_reuses_one_connection(tmp_path: Path):
    store = QuestionStore(tmp_path / "reuse.db")
    with store._conn() as first, store._conn() as second:
        assert first is second
    row = first.execute("PRAGMA journal_mode").fetchone()
    assert row[0].lower() == "wal"


def test_each_thread_gets_its_own_connection(tmp_path: Path):
    store = QuestionStore(tmp_path / "threads.db")
    with store._conn() as main_conn:
        seen: list[int] = []

        def grab():
            with store._conn() as conn:
                seen.append(id(conn))

        threads = [threading.Thread(target=grab) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
    assert len(set(seen)) == 4
    assert all(conn_id != id(main_conn) for conn_id in seen)


def test_writes_are_visible_across_threads(tmp_path: Path):
    store = QuestionStore(tmp_path / "shared.db")
    qid = store.create("Cross-thread?")
    assert store.answer(qid, "yes") is True

    seen: dict[str, str] = {}

    def read_from_thread():
        question = QuestionStore(store.db_path).get(qid)
        assert question is not None
        seen["status"] = question.status

    thread = threading.Thread(target=read_from_thread)
    thread.start()
    thread.join()
    assert seen == {"status": "answered"}
