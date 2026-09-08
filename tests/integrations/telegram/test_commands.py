"""Table-driven tests for the telegram COMMANDS dispatch table.

Each row is (incoming text, queue stub, expected reply): adding a command
means adding a COMMANDS row plus a row here. Uses a FakeApi (records
sends, no HTTP) and a real MessageStore; the question store is only
touched by the answer flow, which test_listener.py covers.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from fleet.core.task import Task
from fleet.integrations.telegram.api import TelegramApi
from fleet.integrations.telegram.commands import COMMANDS, HELP_TEXT, CommandEnv
from fleet.integrations.telegram.messages import MessageStore


class FakeApi(TelegramApi):
    """TelegramApi double: records sends, never touches HTTP."""

    def __init__(self) -> None:
        super().__init__(token="tok")
        self.sent: list[tuple[str, str]] = []

    def fetch_updates(self, offset: int | None) -> list[dict]:
        raise AssertionError("commands never poll")

    async def send(self, chat_id: str, text: str) -> None:
        self.sent.append((chat_id, text))

    async def send_with_id(self, chat_id: str, text: str) -> int | None:
        self.sent.append((chat_id, text))
        return 1


def _env(tmp_path: Path, queue: Any, api: FakeApi) -> CommandEnv:
    """CommandEnv with a static allowlist and fresh reply routing."""
    return CommandEnv(
        queue=queue,
        messages=MessageStore(tmp_path / "qmsgs.json"),
        allowed_ids=lambda: {"123"},
        default_cwd=lambda: None,
    )


def _update(text: str) -> dict:
    return {"update_id": 1, "message": {"from": {"id": 123}, "chat": {"id": 123}, "text": text}}


def _task() -> Task:
    return Task(id="fleet-abc1", title="Fix the bug", description=None, status="open")


def _queue(kind: str) -> MagicMock:
    """Queue stub per table row kind."""
    queue: MagicMock = MagicMock()
    if kind == "created":
        queue.create_task.return_value = _task()
    elif kind == "listed":
        queue.list_in_progress.return_value = [_task()]
        queue.list_ready.return_value = []
    elif kind == "detailed":
        queue.get.return_value = _task()
    elif kind == "get_error":
        queue.get.side_effect = RuntimeError("task not found")
    elif kind == "tasks_error":
        queue.list_in_progress.side_effect = RuntimeError("bd failed")
    return queue


COMMAND_CASES = [
    # (name, incoming text, queue kind, expected reply substring or None for silence)
    ("help", "/help", "blank", HELP_TEXT),
    ("start", "/start", "blank", HELP_TEXT),
    ("help_at_bot", "/help@mybot", "blank", HELP_TEXT),
    ("new_task", "/new_task Fix the bug\nSome details", "created", "fleet-abc1"),
    ("new_task_usage", "/new_task\n", "blank", "Usage: /new_task"),
    ("tasks", "/tasks", "listed", "fleet-abc1"),
    ("tasks_error", "/tasks", "tasks_error", "Could not fetch tasks."),
    ("task_usage", "/task", "blank", "/task <id>"),
    ("task_detail", "/task fleet-abc1", "detailed", "Fix the bug"),
    ("task_unknown", "/task fleet-0000", "get_error", "No task fleet-0000"),
    ("unknown_command", "/bogus", "blank", None),
]


@pytest.mark.parametrize(("name", "text", "queue_kind", "expected"), COMMAND_CASES)
def test_command_dispatch_table(
    tmp_path: Path, name: str, text: str, queue_kind: str, expected: str | None
) -> None:
    """Every COMMANDS row routes and replies (or stays silent) as listed."""
    api = FakeApi()
    asyncio.run(_env(tmp_path, _queue(queue_kind), api).dispatch(api, MagicMock(), _update(text)))
    if expected is None:
        assert api.sent == [], f"{name}: unknown command must stay silent"
    else:
        assert len(api.sent) == 1, f"{name}: exactly one reply"
        assert expected in api.sent[0][1], f"{name}: reply must contain {expected!r}"


def test_commands_registry_lists_every_command() -> None:
    """COMMANDS has one row per supported command, nothing more."""
    assert set(COMMANDS) == {"/new_task", "/tasks", "/task", "/help", "/start"}


def test_new_task_create_args(tmp_path: Path) -> None:
    """The title/description split reaches create_task positionally."""
    api = FakeApi()
    queue = _queue("created")
    asyncio.run(_env(tmp_path, queue, api).dispatch(api, MagicMock(), _update("/new_task T\nD")))
    queue.create_task.assert_called_once_with("T", "D", None, None, None)
