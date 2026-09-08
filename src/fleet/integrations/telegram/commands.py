"""Inbound Telegram command handlers and answer routing.

Called by listener.py through CommandEnv.dispatch: slash commands go
through the COMMANDS table (adding a command is one row), replies to a
question message and plain text go through the answer flow against the
injected question store. Never touches app.state; the serve layer builds
the CommandEnv with queue, reply routing and config providers.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

import structlog

from .api import MAX_TEXT, TelegramApi
from .messages import MessageStore

_log = structlog.get_logger(__name__)

HELP_TEXT = (
    "Fleet bot commands:\n"
    "/new_task <title> - create a task (title may be on the next line; "
    "following lines become the description)\n"
    "/tasks - list open tasks\n"
    "/task <id> - show task details\n"
    "/help - show this help\n"
    "\nReply to a question message to answer it; "
    "with exactly one pending question a plain message answers it directly."
)

_TASKS_CAP = 15  # tasks shown per section in the /tasks reply

Handler = Callable[["CommandContext"], Coroutine[Any, Any, None]]


@dataclass
class CommandContext:
    """One inbound message with everything a handler needs to reply."""

    api: TelegramApi
    store: Any
    queue: Any
    messages: MessageStore
    default_cwd: str | None
    chat_id: str
    text: str
    message: dict


@dataclass
class CommandEnv:
    """Handler dependencies owned by the serve layer (no app.state)."""

    queue: Any
    messages: MessageStore
    allowed_ids: Callable[[], set[str]]
    default_cwd: Callable[[], str | None]

    def is_allowed(self, update: dict, allowed: set[str]) -> bool:
        """True when the update's sender or chat is on the allowlist."""
        return is_allowed(update, allowed)

    async def dispatch(self, api: TelegramApi, store: Any, update: dict) -> None:
        """Route one allowed update: slash command, answer reply, plain text."""
        msg = update.get("message") or {}
        text = msg.get("text") or ""
        chat_id = str((msg.get("chat") or {}).get("id", ""))
        ctx = CommandContext(
            api, store, self.queue, self.messages, self.default_cwd(), chat_id, text, msg
        )
        stripped = text.strip()
        if stripped.startswith("/"):
            name = stripped.split(maxsplit=1)[0].split("@", 1)[0]
            handler = COMMANDS.get(name)
            if handler is not None:
                await handler(ctx)
            return
        reply_to = msg.get("reply_to_message")
        if reply_to is not None:
            await _dispatch_reply(ctx, reply_to)
            return
        if text:
            await _dispatch_plain(ctx)


def parse_allowed_ids(raw: str) -> set[str]:
    """Parse a comma-separated allowlist into stripped id strings."""
    return {s.strip() for s in raw.split(",") if s.strip()}


def is_allowed(update: dict, allowed: set[str]) -> bool:
    """True when the update's sender id or chat id is in *allowed*."""
    msg = update.get("message") or {}
    from_id = str((msg.get("from") or {}).get("id", ""))
    chat_id = str((msg.get("chat") or {}).get("id", ""))
    return (bool(from_id) and from_id in allowed) or (bool(chat_id) and chat_id in allowed)


def parse_new_task_command(text: str) -> tuple[str, str | None] | None:
    """Parse /new_task into (title, description); None when not that command."""
    text = text.strip()
    if not text.startswith("/new_task"):
        return None
    remainder = text[len("/new_task") :]
    if remainder and remainder[0] == "@":  # /new_task@botname variant
        space, newline = remainder.find(" "), remainder.find("\n")
        candidates = [i for i in (space, newline) if i != -1]
        if not candidates:
            return None
        remainder = remainder[min(candidates) :]
    elif remainder and remainder[0] not in (" ", "\n", "\r", "\t"):
        return None
    non_empty = [ln.strip() for ln in remainder.lstrip(" \t").splitlines() if ln.strip()]
    if not non_empty:
        return None
    return non_empty[0], "\n".join(non_empty[1:]) if len(non_empty) > 1 else None


async def answer_question(
    api: TelegramApi, store: Any, chat_id: str, qid: str, raw_text: str
) -> None:
    """Apply a numeric option shortcut, answer the store, confirm by reply."""
    answer: object = raw_text.strip()
    question: dict | None = None
    try:
        idx = int(str(answer))
        question = await asyncio.to_thread(store.get, qid)
        options = (question or {}).get("options") or []
        if options and 1 <= idx <= len(options):
            answer = options[idx - 1]
    except ValueError:
        pass
    result = await asyncio.to_thread(store.answer_result, qid, answer, answered_by="telegram")
    if result["ok"]:
        if question is None:
            question = await asyncio.to_thread(store.get, qid)
        label = (question or {}).get("agent_id") or qid
        await api.send(chat_id, f"Answered [{label}]")
    elif result["status"] in ("answered", "conflict"):
        await api.send(chat_id, "Question already answered")
    else:
        await api.send(chat_id, "Unknown or expired question")


async def _dispatch_reply(ctx: CommandContext, reply_to: dict) -> None:
    """Answer the question a reply points at, or explain an unknown mapping."""
    qid = ctx.messages.lookup(reply_to.get("message_id") or 0)
    if qid and ctx.chat_id:
        await answer_question(ctx.api, ctx.store, ctx.chat_id, qid, ctx.text)
    elif ctx.chat_id:
        await ctx.api.send(ctx.chat_id, "Unknown or expired question")


async def _dispatch_plain(ctx: CommandContext) -> None:
    """Plain text answers the single pending question, or hints at replies."""
    pending = await asyncio.to_thread(ctx.store.count_pending)
    if pending == 1:
        questions = await asyncio.to_thread(ctx.store.fetch_pending, 1)
        if questions and ctx.chat_id:
            await answer_question(ctx.api, ctx.store, ctx.chat_id, questions[0]["id"], ctx.text)
    elif pending > 1 and ctx.chat_id:
        await ctx.api.send(
            ctx.chat_id,
            f"{pending} questions pending - reply directly "
            "to the specific question message to answer it",
        )


async def handle_new_task(ctx: CommandContext) -> None:
    """Create a task from /new_task <title> plus optional description lines."""
    parsed = parse_new_task_command(ctx.text)
    if parsed is None:
        if ctx.chat_id:
            await ctx.api.send(
                ctx.chat_id, "Usage: /new_task <title>\n[optional description lines]"
            )
        return
    title, description = parsed
    try:
        task = await asyncio.to_thread(
            ctx.queue.create_task, title, description, None, None, ctx.default_cwd or None
        )
    except Exception as exc:
        _log.error("telegram.inbound: create_task failed", error=str(exc))
        reply = f"Error creating task: {exc}"
    else:
        _log.info("telegram.inbound: created task", task_id=task.id, title=task.title)
        reply = f"Created task {task.id}: {task.title}"
    if ctx.chat_id:
        await ctx.api.send(ctx.chat_id, reply)


async def handle_tasks(ctx: CommandContext) -> None:
    """Reply with the open task list, capped per section."""
    if not ctx.chat_id:
        return
    try:
        in_progress = await asyncio.to_thread(ctx.queue.list_in_progress)
        ready = await asyncio.to_thread(ctx.queue.list_ready)
    except Exception as exc:
        _log.warning("telegram.inbound: /tasks failed", error=str(exc))
        await ctx.api.send(ctx.chat_id, "Could not fetch tasks.")
        return
    sections = [
        f"{label}:\n"
        + "\n".join(f"- {t.id} {t.title}" for t in tasks[:_TASKS_CAP])
        + (f"\n... and {len(tasks) - _TASKS_CAP} more" if len(tasks) > _TASKS_CAP else "")
        for label, tasks in (("In progress", in_progress), ("Ready", ready))
        if tasks
    ]
    await ctx.api.send(ctx.chat_id, "\n\n".join(sections) if sections else "No open tasks.")


async def handle_task(ctx: CommandContext) -> None:
    """Reply with one task's details, or usage when no id is given."""
    if not ctx.chat_id:
        return
    parts = ctx.text.strip().split(maxsplit=1)
    task_id = parts[1].split()[0] if len(parts) > 1 else None
    if not task_id:
        await ctx.api.send(
            ctx.chat_id,
            "Usage: /task <id> - show task details; "
            "/tasks - list open tasks; "
            "/new_task <title> - create a task",
        )
        return
    try:
        task = await asyncio.to_thread(ctx.queue.get, task_id)
    except Exception as exc:
        _log.warning("telegram.inbound: /task get failed", task_id=task_id, error=str(exc))
        reply = f"No task {task_id}. To create a task use /new_task <title>"
    else:
        header = f"ID: {task.id}\nStatus: {task.status}\nTitle: {task.title}"
        if task.description:
            desc = task.description[: MAX_TEXT - len(header) - 2]
            reply = header + "\n\n" + desc
        else:
            reply = header
    await ctx.api.send(ctx.chat_id, reply)


async def handle_help(ctx: CommandContext) -> None:
    """Reply with the command list."""
    if ctx.chat_id:
        await ctx.api.send(ctx.chat_id, HELP_TEXT)


COMMANDS: dict[str, Handler] = {
    "/new_task": handle_new_task,
    "/tasks": handle_tasks,
    "/task": handle_task,
    "/help": handle_help,
    "/start": handle_help,
}
