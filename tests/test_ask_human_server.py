"""Async-wait tests for the vendored ask_human MCP server's ``_await_answer``.

Adapted from the upstream agent-chat test suite (~/git/claude/mcp/ask_human).
These cover the property the indefinite-wait design rests on: the server waits
WITHOUT blocking the event loop (so the MCP connection stays alive across long
waits), returns as soon as the question is answered out-of-band, and honors
``timeout_s`` -> ``default``.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from fleet.ask_human.server import _await_answer, _result
from fleet.ask_human.store import QuestionStore


def _store(tmp_path: Path) -> QuestionStore:
    return QuestionStore(tmp_path / "q.db")


def test_await_answer_returns_when_answered(tmp_path: Path):
    s = _store(tmp_path)
    qid = s.create("Deploy?", options=["yes", "no"], agent_id="a")

    async def scenario():
        async def operator():
            await asyncio.sleep(0.15)
            assert s.answer(qid, "yes", answered_by="web")

        task = asyncio.create_task(operator())
        q = await _await_answer(s, qid, ctx=None, poll_interval=0.02)
        await task
        return q

    q = asyncio.run(scenario())
    assert q["status"] == "answered"
    assert q["answer"] == "yes"
    assert q["answered_by"] == "web"


def test_await_answer_times_out_to_default(tmp_path: Path):
    s = _store(tmp_path)
    qid = s.create("Proceed?", timeout_s=0.1, default_answer="no")
    q = asyncio.run(_await_answer(s, qid, ctx=None, poll_interval=0.02))
    assert q["status"] == "expired"
    assert q["answer"] == "no"


def test_result_surfaces_note_and_keys(tmp_path: Path):
    # The agent only sees what `_result` projects — a missing `note` key here
    # would silently drop the operator's correction. Guard the contract.
    s = _store(tmp_path)
    qid = s.create("Deploy?", options=["yes", "no"], agent_id="a")
    assert s.answer(qid, "yes", note="wait for the migration first", answered_by="web")
    r = _result(s.get(qid))
    assert set(r) == {"id", "status", "answer", "note", "answered_by"}
    assert r["answer"] == "yes"
    assert r["note"] == "wait for the migration first"


def test_await_answer_round_trips_note_only_reply(tmp_path: Path):
    # End-to-end: the operator picks no option and replies purely in free text;
    # the agent must receive answer=None with the substance in `note`.
    s = _store(tmp_path)
    qid = s.create("Which DB?", options=["postgres", "mysql"], agent_id="a")

    async def scenario():
        async def operator():
            await asyncio.sleep(0.15)
            assert s.answer(qid, None, note="use sqlite instead", answered_by="web")

        task = asyncio.create_task(operator())
        q = await _await_answer(s, qid, ctx=None, poll_interval=0.02)
        await task
        return _result(q)

    r = asyncio.run(scenario())
    assert r["status"] == "answered"
    assert r["answer"] is None
    assert r["note"] == "use sqlite instead"


def test_await_answer_does_not_block_event_loop(tmp_path: Path):
    # While waiting, a concurrent coroutine must keep running — this is what
    # proves we ``await`` rather than ``time.sleep`` (a blocking wait would
    # freeze the loop and starve the ticker, which is exactly what dropped the
    # MCP connection before).
    s = _store(tmp_path)
    qid = s.create("hold")
    ticks = 0

    async def scenario():
        nonlocal ticks

        async def ticker():
            nonlocal ticks
            while True:
                await asyncio.sleep(0.02)
                ticks += 1

        async def answerer():
            await asyncio.sleep(0.2)
            s.answer(qid, "done")

        t = asyncio.create_task(ticker())
        a = asyncio.create_task(answerer())
        q = await _await_answer(s, qid, ctx=None, poll_interval=0.02)
        t.cancel()
        await a
        return q

    q = asyncio.run(scenario())
    assert q["status"] == "answered"
    assert ticks >= 3  # the loop kept making progress while we waited
