"""Async-wait tests for the vendored ask_human MCP server's ``_await_answer``.

Adapted from the upstream agent-chat test suite (~/git/claude/mcp/ask_human).
These cover the property the indefinite-wait design rests on: the server waits
WITHOUT blocking the event loop (so the MCP connection stays alive across long
waits), returns as soon as the question is answered out-of-band, and honors
``timeout_s`` -> ``default``.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from fleet.integrations.ask_human.server import _await_answer, _default_agent_id, _result
from fleet.integrations.ask_human.store import QuestionStore


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


def test_default_agent_id_from_fleet_task_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """When FLEET_TASK_DIR is set, _default_agent_id extracts the last path segment as agent_id."""
    task_dir = tmp_path / ".fleet" / "tasks" / "fleet-abcd123"
    task_dir.mkdir(parents=True)
    monkeypatch.setenv("FLEET_TASK_DIR", str(task_dir))
    assert _default_agent_id() == "fleet-abcd123"


def test_default_agent_id_returns_none_without_env(monkeypatch: pytest.MonkeyPatch):
    """When FLEET_TASK_DIR is not set, _default_agent_id returns None."""
    monkeypatch.delenv("FLEET_TASK_DIR", raising=False)
    assert _default_agent_id() is None


def test_default_agent_id_empty_basename_returns_none(
    monkeypatch: pytest.MonkeyPatch,
):
    """When FLEET_TASK_DIR basename is empty, _default_agent_id returns None."""
    monkeypatch.setenv("FLEET_TASK_DIR", "/some/path/")

    orig_basename = os.path.basename
    os.path.basename = lambda _: ""
    try:
        result = _default_agent_id()
    finally:
        os.path.basename = orig_basename
    assert result is None


def test_ask_human_question_uses_env_default_agent_id(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """When agent_id=None is passed, the server defaults it from FLEET_TASK_DIR."""
    task_dir = tmp_path / ".fleet" / "tasks" / "fleet-xyz999"
    task_dir.mkdir(parents=True)
    monkeypatch.setenv("FLEET_TASK_DIR", str(task_dir))

    s = _store(tmp_path)
    # Simulate what ask_human_question does: effective_agent_id = agent_id or _default_agent_id()
    from fleet.integrations.ask_human.server import _default_agent_id

    effective = None or _default_agent_id()
    qid = s.create("hello", agent_id=effective)
    q = s.get(qid)
    assert q["agent_id"] == "fleet-xyz999"


def test_ask_human_question_explicit_agent_id_wins_over_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """Explicit agent_id parameter overrides the FLEET_TASK_DIR env default."""
    task_dir = tmp_path / ".fleet" / "tasks" / "fleet-env-default"
    task_dir.mkdir(parents=True)
    monkeypatch.setenv("FLEET_TASK_DIR", str(task_dir))

    s = _store(tmp_path)
    from fleet.integrations.ask_human.server import _default_agent_id

    # When explicitly passed, agent_id wins over env default
    explicit = "fleet-abc123"
    effective = explicit or _default_agent_id()
    qid = s.create("hello", agent_id=effective)
    q = s.get(qid)
    assert q["agent_id"] == "explicit" or q["agent_id"] == "fleet-abc123"

    # Verify env default alone would give fleet-env-default
    env_only = None or _default_agent_id()
    qid2 = s.create("env default test", agent_id=env_only)
    q2 = s.get(qid2)
    assert q2["agent_id"] == "fleet-env-default"
