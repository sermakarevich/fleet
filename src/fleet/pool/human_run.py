"""Ask one human question for a step run (DESIGN.md §3.1, §3.8).

Idempotent per ``(task_id, context)``: an already-answered question is
returned without asking, an already-pending one is waited on, otherwise a
new question is asked. The question store is passed in behind the
:class:`AskStore` protocol so this module never imports
``fleet.integrations`` (layering). Knows nothing about flows or runs.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class HumanAnswer:
    """A resolved human answer: the chosen option (or typed text) plus note."""

    answer: str
    note: str  # operator free text ("" when none)
    question_id: str
    cancelled: bool = False


class AskStore(Protocol):
    """What the pool needs from QuestionStore, nothing more."""

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
    ) -> str: ...
    def find_pending(self, task_id: str | None, context: str | None) -> Any: ...
    def fetch_answered_for_task(self, task_id: str, context: str | None = None) -> list[Any]: ...


def _field(row: Any, key: str) -> Any:
    """Read ``key`` off a Question row, a mapping, or any attribute holder."""
    getter = getattr(row, "get", None)
    if callable(getter):
        return getter(key)
    if isinstance(row, Mapping):
        return row.get(key)
    return getattr(row, key, None)


def _answer_text(raw: Any) -> str:
    """Render a stored answer value: lists (multi-select) join with ", "."""
    if raw is None:
        return ""
    if isinstance(raw, list):
        return ", ".join(str(item) for item in raw)
    if isinstance(raw, str):
        return raw
    return str(raw)


def _note_text(raw: Any) -> str:
    """Render a stored note value ("" when none)."""
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    return str(raw)


def _from_row(row: Any) -> HumanAnswer:
    """Build a HumanAnswer from a resolved question row."""
    return HumanAnswer(
        answer=_answer_text(_field(row, "answer")),
        note=_note_text(_field(row, "note")),
        question_id=str(_field(row, "id") or ""),
        cancelled=_field(row, "status") == "cancelled",
    )


async def ask_human(
    store: AskStore,
    prompt: str,
    *,
    task_id: str,
    context: str,
    options: Sequence[str] | None = None,
    poll_s: float = 5.0,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> HumanAnswer:
    """Ask ``prompt`` once per (task_id, context), waiting for the answer.

    Returns the existing answered question when the pair was asked before,
    waits on the existing pending question when one is in flight, else asks
    a new question and polls ``fetch_answered_for_task`` every ``poll_s``
    until it resolves. A question cancelled mid-wait (pending row gone,
    no answer) returns ``cancelled=True``. ``sleep`` is injectable so
    tests never wait on wall time.
    """
    answered = store.fetch_answered_for_task(task_id, context)
    if answered:
        return _from_row(answered[-1])
    pending = store.find_pending(task_id, context)
    if pending is not None:
        qid = str(_field(pending, "id") or "")
    else:
        qid = store.ask(
            prompt,
            list(options) if options is not None else None,
            task_id=task_id,
            context=context,
        )
    while True:
        await sleep(poll_s)
        answered = store.fetch_answered_for_task(task_id, context)
        if answered:
            return _from_row(answered[-1])
        if store.find_pending(task_id, context) is None:
            return HumanAnswer(answer="", note="", question_id=qid, cancelled=True)


def write_human_outputs(step_dir: Path, answer: HumanAnswer) -> Path:
    """Write ``outputs/outputs.json`` = {"answer", "note", "question_id"}."""
    path = step_dir / "outputs" / "outputs.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"answer": answer.answer, "note": answer.note, "question_id": answer.question_id},
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return path


def is_yes(answer: HumanAnswer) -> bool:
    """True when the answer is an affirmation: yes/y/ok/true (any case)."""
    return answer.answer.strip().lower() in {"yes", "y", "ok", "true"}
