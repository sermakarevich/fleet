"""Tests for fleet.pool.human_run against a fake store (public methods only)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import pytest

from fleet.pool.human_run import (
    HumanAnswer,
    ask_human,
    is_yes,
    write_human_outputs,
)
from tests.pool.conftest import FakeStore, answer_on_first_tick


def _answer_on_first_tick(
    store: FakeStore, answer: Any, note: str | None
) -> Callable[[float], Awaitable[None]]:
    """A sleep stub that resolves the pending question, then returns."""
    return answer_on_first_tick(store, answer, note)


def test_asks_once_and_returns_answer_and_note() -> None:
    """A fresh pair asks once, polls, and returns the answer plus note."""
    store = FakeStore()
    result = asyncio.run(
        ask_human(
            store,
            "Continue?",
            task_id="task-1",
            context="ctx-1",
            options=["yes", "no"],
            poll_s=0.01,
            sleep=_answer_on_first_tick(store, "yes", "posted"),
        )
    )
    assert isinstance(result, HumanAnswer)
    assert result.answer == "yes"
    assert result.note == "posted"
    assert result.question_id == "q1"
    assert not result.cancelled
    assert store.ask_count == 1


def test_existing_answered_row_returned_without_asking() -> None:
    """An answered pair never asks again."""
    store = FakeStore()
    store.ask("Continue?", ["yes", "no"], task_id="task-1", context="ctx-1")
    store.answer("q1", "no", note="not yet")

    async def _fail(_delay: float) -> None:
        raise AssertionError("must not poll when already answered")

    result = asyncio.run(
        ask_human(store, "Continue?", task_id="task-1", context="ctx-1", sleep=_fail)
    )
    assert (result.answer, result.note, result.question_id) == ("no", "not yet", "q1")
    assert store.ask_count == 1


def test_pending_row_reused() -> None:
    """An in-flight pending question is waited on, not duplicated."""
    store = FakeStore()
    store.ask("Continue?", ["yes", "no"], task_id="task-1", context="ctx-1")
    result = asyncio.run(
        ask_human(
            store,
            "Continue?",
            task_id="task-1",
            context="ctx-1",
            poll_s=0.01,
            sleep=_answer_on_first_tick(store, "ok", None),
        )
    )
    assert result.answer == "ok"
    assert result.note == ""
    assert result.question_id == "q1"
    assert store.ask_count == 1


def test_multi_select_answers_joined() -> None:
    """A list answer (multi-select) joins with ", "."""
    store = FakeStore()
    result = asyncio.run(
        ask_human(
            store,
            "Pick all that apply",
            task_id="task-1",
            context="ctx-1",
            poll_s=0.01,
            sleep=_answer_on_first_tick(store, ["alpha", "beta"], None),
        )
    )
    assert result.answer == "alpha, beta"


def test_cancelled_row_returns_cancelled() -> None:
    """A question cancelled mid-wait resolves to cancelled=True."""

    async def _cancel(_delay: float) -> None:
        store.cancel("q1")

    store = FakeStore()
    result = asyncio.run(
        ask_human(store, "Continue?", task_id="task-1", context="ctx-1", poll_s=0.01, sleep=_cancel)
    )
    assert result.cancelled
    assert result.question_id == "q1"
    assert store.ask_count == 1


def test_note_without_answer_keeps_note() -> None:
    """An operator note with no chosen option keeps answer empty, note full."""
    store = FakeStore()
    result = asyncio.run(
        ask_human(
            store,
            "Continue?",
            task_id="task-1",
            context="ctx-1",
            poll_s=0.01,
            sleep=_answer_on_first_tick(store, None, "do the other thing"),
        )
    )
    assert result.answer == ""
    assert result.note == "do the other thing"
    assert not result.cancelled


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("yes", True),
        ("Y", True),
        ("  ok  ", True),
        ("TRUE", True),
        ("no", False),
        ("n", False),
        ("maybe", False),
        ("", False),
        ("yesterday", False),
    ],
)
def test_is_yes_cases(text: str, expected: bool) -> None:
    """Affirmations pass case-insensitively stripped; everything else fails."""
    assert is_yes(HumanAnswer(answer=text, note="", question_id="q1")) is expected


def test_write_human_outputs(tmp_path: Path) -> None:
    """Human outputs carry answer, note and question id."""
    answer = HumanAnswer(answer="yes", note="posted", question_id="q7")
    path = write_human_outputs(tmp_path / "step", answer)
    assert path == tmp_path / "step" / "outputs" / "outputs.json"
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "answer": "yes",
        "note": "posted",
        "question_id": "q7",
    }
