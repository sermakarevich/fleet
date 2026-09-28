"""Shared pool-test fakes: an in-memory AskStore plus answer-on-tick sleep."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any


class FakeRow:
    """A Question-like row exposing .get (the pool's only read contract)."""

    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)


class FakeStore:
    """An in-memory AskStore: ask/find_pending/fetch_answered_for_task only."""

    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}
        self.ask_count = 0
        self._next = 0

    def ask(
        self,
        prompt: str,
        options: list[str] | None = None,
        *,
        task_id: str | None = None,
        context: str | None = None,
        agent_id: str = "triage",
        priority: int = 0,
        multi_select: bool = False,
    ) -> str:
        self.ask_count += 1
        self._next += 1
        qid = f"q{self._next}"
        self.rows[qid] = {
            "id": qid,
            "prompt": prompt,
            "options": options,
            "status": "pending",
            "answer": None,
            "note": None,
            "task_id": task_id,
            "context": context,
        }
        return qid

    def find_pending(self, task_id: str | None, context: str | None) -> Any:
        for row in self.rows.values():
            if (
                row["status"] == "pending"
                and row["task_id"] == task_id
                and row["context"] == context
            ):
                return FakeRow(row)
        return None

    def fetch_answered_for_task(self, task_id: str, context: str | None = None) -> list[Any]:
        return [
            FakeRow(row)
            for row in self.rows.values()
            if row["status"] == "answered"
            and row["task_id"] == task_id
            and (context is None or row["context"] == context)
        ]

    def answer(self, qid: str, answer: Any, note: str | None = None) -> None:
        self.rows[qid]["status"] = "answered"
        self.rows[qid]["answer"] = answer
        self.rows[qid]["note"] = note

    def cancel(self, qid: str) -> None:
        self.rows[qid]["status"] = "cancelled"


def answer_on_first_tick(
    store: FakeStore,
    answer: Any,
    note: str | None,
    task_id: str = "task-1",
    context: str = "ctx-1",
) -> Callable[[float], Awaitable[None]]:
    """A sleep stub that resolves the pending question, then returns."""

    async def _sleep(_delay: float) -> None:
        pending = store.find_pending(task_id, context)
        if pending is not None:
            store.answer(pending.get("id"), answer, note=note)

    return _sleep
