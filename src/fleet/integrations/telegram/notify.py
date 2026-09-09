"""Telegram notifications for new ask_human questions.

Called by the serve question poller (serve/app.py): format each pending
question and send it via TelegramApi, recording message ids in the
MessageStore so operator replies route back (commands.answer_question).
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from .api import TelegramApi
from .messages import MessageStore

if TYPE_CHECKING:
    from fleet.integrations.ask_human.store import Question


def format_question_message(question: Question | dict) -> str:
    """Render one question as '[agent] prompt' plus a numbered option list."""
    text = f"[{question.get('agent_id') or 'unknown'}] {question.get('prompt') or ''}"
    options = question.get("options")
    if options:
        opts = options if isinstance(options, list) else [str(options)]
        text += "\n" + "\n".join(f"  {i + 1}. {o}" for i, o in enumerate(opts))
    return text


async def notify_new_questions(
    api: TelegramApi,
    store: Any,
    messages: MessageStore,
    chat_id: str,
    watermark: float,
) -> float:
    """Send every question newer than *watermark*; return the new watermark."""
    questions = await asyncio.to_thread(store.fetch_new, watermark)
    new_watermark = watermark
    for question in questions:
        message_id = await api.send_with_id(chat_id, format_question_message(question))
        if message_id is not None and question.get("id"):
            messages.record(message_id, question["id"])
        new_watermark = max(new_watermark, float(question.get("created_at") or 0))
    return new_watermark
