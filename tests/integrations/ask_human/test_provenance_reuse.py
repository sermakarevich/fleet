"""Provenance-question reuse: a retried plan step blocks on the pending question.

Regression test for the fleet-sa6ku double-ask (two pending rows for the
same bead + source URL ~70s apart). Keying the question on
(task_id, source_url) means the retry creates no new row and waits on the
existing one instead.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from fleet.integrations.ask_human import server
from fleet.integrations.ask_human.store import QuestionStore

SOURCE = "https://github.com/abdufelsayed/talkio"


def _store(tmp_path: Path) -> QuestionStore:
    return QuestionStore(tmp_path / "q.db")


def _use_store(store: QuestionStore):
    """Point the MCP tool at a tmp store; restore the global afterwards."""

    class _Guard:
        def __enter__(self):
            self.prev = server._StoreBox.store
            server._StoreBox.store = store
            return store

        def __exit__(self, *args):
            server._StoreBox.store = self.prev

    return _Guard()


def test_create_persists_key_and_find_pending_returns_oldest(tmp_path: Path):
    s = _store(tmp_path)
    q1 = s.create("first?", task_id="fleet-sa6ku", context=SOURCE)
    q2 = s.create("second?", task_id="fleet-sa6ku", context=SOURCE)
    assert s.find_pending("fleet-sa6ku", SOURCE)["id"] == q1
    assert s.find_pending("fleet-sa6ku", SOURCE)["id"] != q2
    # Empty keys never match, so unkeyed questions never collapse.
    assert s.find_pending(None, SOURCE) is None
    assert s.find_pending("fleet-sa6ku", None) is None
    assert s.find_pending("", "") is None
    # Other pairs do not match.
    assert s.find_pending("fleet-sa6ku", "https://other.example/") is None
    assert s.find_pending("fleet-other", SOURCE) is None


def test_find_pending_ignores_resolved(tmp_path: Path):
    s = _store(tmp_path)
    qid = s.create("collision?", task_id="t", context=SOURCE)
    s.answer(qid, "research/Talkio", answered_by="op")
    assert s.find_pending("t", SOURCE) is None


def test_retry_reuses_pending_question_creates_no_new_row(tmp_path: Path):
    s = _store(tmp_path)
    first = s.create(
        "provenance check found the SAME Source URL in TWO folders...",
        options=["research/Talkio", "investment/2026-09-22-Talkio"],
        task_id="fleet-sa6ku",
        context=SOURCE,
    )

    async def scenario():
        async def operator():
            await asyncio.sleep(0.1)
            assert s.answer(first, "research/Talkio", answered_by="op")

        op = asyncio.create_task(operator())
        with _use_store(s):
            # Second attempt words the prompt differently but keys the same.
            result = await server.ask_human_question(
                "provenance check for Source https://github.com/abdufelsayed/talkio "
                "found matches in BOTH existing folders...",
                options=["research/Talkio", "investment/2026-09-22-Talkio"],
                task_id="fleet-sa6ku",
                context=SOURCE,
                ctx=None,
            )
        await op
        return result

    result = asyncio.run(scenario())
    assert result["id"] == first
    assert result["status"] == "answered"
    assert result["answer"] == "research/Talkio"
    assert s.count_pending() == 0
    # No second row was ever created: exactly one question total.
    assert [q["id"] for q in s.fetch_pending_for_task("fleet-sa6ku")] == []


def test_different_source_asks_fresh(tmp_path: Path):
    s = _store(tmp_path)
    s.create("collision?", task_id="t", context=SOURCE)

    async def scenario():
        async def operator():
            await asyncio.sleep(0.1)
            pending = s.fetch_pending_for_task("t")
            assert len(pending) == 2
            for q in pending:
                s.answer(q["id"], "x", answered_by="op")

        op = asyncio.create_task(operator())
        with _use_store(s):
            result = await server.ask_human_question(
                "collision?", task_id="t", context="https://other.example/", ctx=None
            )
        await op
        return result

    result = asyncio.run(scenario())
    assert result["answer"] == "x"


def test_unkeyed_questions_keep_old_behavior(tmp_path: Path):
    # No task_id/context: every call inserts (backwards compatible).
    s = _store(tmp_path)

    async def scenario():
        async def operator():
            answered = 0
            while answered < 2:
                await asyncio.sleep(0.05)
                for q in s.list_pending():
                    if s.answer(q["id"], "x", answered_by="op"):
                        answered += 1

        op = asyncio.create_task(operator())
        with _use_store(s):
            r1 = await server.ask_human_question("q?", ctx=None)
            r2 = await server.ask_human_question("q?", ctx=None)
        await op
        return r1, r2

    r1, r2 = asyncio.run(scenario())
    assert r1["id"] != r2["id"]


def test_env_default_task_id_dedupes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    # The worker omits task_id; FLEET_TASK_DIR supplies it, context keys it.
    task_dir = tmp_path / ".fleet" / "tasks" / "fleet-sa6ku"
    task_dir.mkdir(parents=True)
    monkeypatch.setenv("FLEET_TASK_DIR", str(task_dir))
    s = _store(tmp_path)
    first = s.create("collision?", task_id="fleet-sa6ku", context=SOURCE)

    async def scenario():
        async def operator():
            await asyncio.sleep(0.1)
            assert s.answer(first, "research/Talkio", answered_by="op")

        op = asyncio.create_task(operator())
        with _use_store(s):
            result = await server.ask_human_question("collision?", context=SOURCE, ctx=None)
        await op
        return result

    assert asyncio.run(scenario())["id"] == first


def test_answered_question_does_not_suppress_reask(tmp_path: Path):
    s = _store(tmp_path)
    qid = s.create("collision?", task_id="t", context=SOURCE)
    s.answer(qid, "research/Talkio", answered_by="op")

    async def scenario():
        async def operator():
            await asyncio.sleep(0.1)
            pending = s.fetch_pending_for_task("t", SOURCE)
            assert len(pending) == 1
            assert pending[0]["id"] != qid
            s.answer(pending[0]["id"], "y", answered_by="op")

        op = asyncio.create_task(operator())
        with _use_store(s):
            result = await server.ask_human_question(
                "collision?", task_id="t", context=SOURCE, ctx=None
            )
        await op
        return result

    result = asyncio.run(scenario())
    assert result["id"] != qid
    assert result["answer"] == "y"
