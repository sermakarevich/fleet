"""Tests for the inbound listener loop (unit under test: integrations/telegram/listener.py).

Updates come from a scripted ``FakeTelegramApi`` and pauses from a recording
``sleep_fn`` — no ``asyncio.to_thread``/``sleep`` patching, no env patching.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from fleet.core.config import RuntimeConfig
from fleet.core.task import Task
from fleet.integrations.telegram.listener import inbound_listener
from fleet.integrations.telegram.messages import OffsetStore
from tests.helpers.fakes import FakeTelegramApi
from tests.integrations.telegram.conftest import run_listener, scripted_updates


def test_load_offset_missing_file(tmp_path: Path) -> None:
    assert OffsetStore(tmp_path / "offset").load() is None


def test_save_and_load_offset(tmp_path: Path) -> None:
    offsets = OffsetStore(tmp_path / "offset")
    offsets.save(42)
    assert offsets.load() == 42


def test_save_offset_creates_parent_dirs(tmp_path: Path) -> None:
    offsets = OffsetStore(tmp_path / "sub" / "dir" / "offset")
    offsets.save(99)
    assert offsets.load() == 99


def test_load_offset_invalid_content(tmp_path: Path) -> None:
    path = tmp_path / "offset"
    path.write_text("not-a-number")
    assert OffsetStore(path).load() is None


def test_inbound_listener_exits_when_no_token(tmp_path: Path) -> None:
    api = FakeTelegramApi("")
    asyncio.run(inbound_listener(api, MagicMock(), MagicMock(), OffsetStore(tmp_path / "offset")))
    assert api.calls == [], "No polling without a token"


def test_inbound_listener_skips_polling_when_allowlist_empty(tmp_path: Path) -> None:
    config = RuntimeConfig(telegram_allowed_ids="")
    app = MagicMock()
    app.state.fleet_state.config = config
    api = FakeTelegramApi("tok")
    pauses: list[float] = []

    async def _record_then_stop(delay: float) -> None:
        pauses.append(delay)
        raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(run_listener(app, tmp_path, api=api, sleep_fn=_record_then_stop))

    assert api.calls == [], "getUpdates must not be called when allowlist is empty"
    assert len(pauses) == 1


def test_inbound_listener_rejects_unknown_sender(tmp_path: Path) -> None:

    config = RuntimeConfig(telegram_allowed_ids="999")  # only 999 is allowed
    app = MagicMock()
    app.state.fleet_state.config = config

    updates = [
        {
            "update_id": 10,
            "message": {"from": {"id": 111}, "chat": {"id": 111}, "text": "/new_task Bad actor"},
        }
    ]
    api = scripted_updates(updates)

    sent = api.sent
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(run_listener(app, tmp_path, api=api))

    assert sent == [], "Rejected sender must get no reply"
    # Offset should have advanced past the rejected update
    assert OffsetStore(tmp_path / "offset").load() == 11


def test_inbound_listener_creates_task_and_replies(tmp_path: Path) -> None:

    config = RuntimeConfig(telegram_allowed_ids="123", telegram_default_cwd="/my/project")
    app = MagicMock()
    app.state.fleet_state.config = config

    fake_task = Task(id="fleet-abc1", title="Fix the bug", description=None, status="open")
    app.state.queue.create_task.return_value = fake_task

    updates = [
        {
            "update_id": 5,
            "message": {
                "from": {"id": 123},
                "chat": {"id": 123},
                "text": "/new_task Fix the bug\nSome details",
            },
        }
    ]
    api = scripted_updates(updates)

    sent = api.sent
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(run_listener(app, tmp_path, api=api))

    assert len(sent) == 1
    assert "fleet-abc1" in sent[0][1]
    assert OffsetStore(tmp_path / "offset").load() == 6
    app.state.queue.create_task.assert_called_once_with(
        "Fix the bug", "Some details", None, None, "/my/project"
    )


def test_inbound_listener_backs_off_on_network_error(tmp_path: Path) -> None:
    config = RuntimeConfig(telegram_allowed_ids="123")
    app = MagicMock()
    app.state.fleet_state.config = config
    api = FakeTelegramApi(
        "tok",
        updates=[OSError("network failure"), OSError("network failure"), asyncio.CancelledError()],
    )
    pauses: list[float] = []

    async def _record(delay: float) -> None:
        pauses.append(delay)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(run_listener(app, tmp_path, api=api, sleep_fn=_record))

    assert len(pauses) >= 2
    # Backoff doubles: second sleep should be >= first
    assert pauses[1] >= pauses[0]


def test_inbound_listener_malformed_task_sends_error_reply(tmp_path: Path) -> None:
    """Malformed /new_task command (empty title) sends error reply; no task is created."""

    config = RuntimeConfig(telegram_allowed_ids="123")
    app = MagicMock()
    app.state.fleet_state.config = config

    updates = [
        {
            "update_id": 20,
            "message": {
                "from": {"id": 123},
                "chat": {"id": 123},
                "text": "/new_task\n",  # empty title → malformed
            },
        }
    ]
    api = scripted_updates(updates)

    sent = api.sent
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(run_listener(app, tmp_path, api=api))

    app.state.queue.create_task.assert_not_called()
    assert len(sent) == 1, "Expected exactly one error reply"
    assert "usage" in sent[0][1].lower() or "Usage" in sent[0][1]
    assert OffsetStore(tmp_path / "offset").load() == 21


def test_inbound_listener_new_task_botname_creates_task(tmp_path: Path) -> None:
    """/new_task@mybot <title> creates a task just like /new_task <title>."""

    config = RuntimeConfig(telegram_allowed_ids="123", telegram_default_cwd="")
    app = MagicMock()
    app.state.fleet_state.config = config

    fake_task = Task(id="fleet-bot1", title="Bot task", description=None, status="open")
    app.state.queue.create_task.return_value = fake_task

    updates = [
        {
            "update_id": 30,
            "message": {
                "from": {"id": 123},
                "chat": {"id": 123},
                "text": "/new_task@mybot Bot task",
            },
        }
    ]
    api = scripted_updates(updates)

    sent = api.sent
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(run_listener(app, tmp_path, api=api))

    assert len(sent) == 1
    assert "fleet-bot1" in sent[0][1]
    app.state.queue.create_task.assert_called_once_with("Bot task", None, None, None, None)


def test_inbound_listener_tasks_command_lists_tasks(tmp_path: Path) -> None:
    """/tasks replies with in-progress and ready task sections."""

    config = RuntimeConfig(telegram_allowed_ids="123")
    app = MagicMock()
    app.state.fleet_state.config = config

    app.state.queue.list_in_progress.return_value = [
        Task(id="fleet-aaa1", title="Task A", description=None, status="in_progress")
    ]
    app.state.queue.list_ready.return_value = [
        Task(id="fleet-bbb1", title="Task B", description=None, status="open")
    ]

    updates = [
        {"update_id": 40, "message": {"from": {"id": 123}, "chat": {"id": 123}, "text": "/tasks"}}
    ]
    api = scripted_updates(updates)

    sent = api.sent
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(run_listener(app, tmp_path, api=api))

    app.state.queue.create_task.assert_not_called()
    assert len(sent) == 1
    reply = sent[0][1]
    assert "In progress" in reply
    assert "fleet-aaa1" in reply
    assert "Task A" in reply
    assert "Ready" in reply
    assert "fleet-bbb1" in reply
    assert "Task B" in reply


def test_inbound_listener_tasks_both_empty_replies_no_open_tasks(tmp_path: Path) -> None:
    """/tasks with no tasks in any state replies 'No open tasks.'"""

    config = RuntimeConfig(telegram_allowed_ids="123")
    app = MagicMock()
    app.state.fleet_state.config = config
    app.state.queue.list_in_progress.return_value = []
    app.state.queue.list_ready.return_value = []

    updates = [
        {"update_id": 43, "message": {"from": {"id": 123}, "chat": {"id": 123}, "text": "/tasks"}}
    ]
    api = scripted_updates(updates)

    sent = api.sent
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(run_listener(app, tmp_path, api=api))

    assert len(sent) == 1
    assert sent[0][1] == "No open tasks."


def test_inbound_listener_tasks_queue_error_replies_could_not_fetch(tmp_path: Path) -> None:
    """Queue error during /tasks sends 'Could not fetch tasks.' and keeps loop alive."""

    config = RuntimeConfig(telegram_allowed_ids="123")
    app = MagicMock()
    app.state.fleet_state.config = config
    app.state.queue.list_in_progress.side_effect = RuntimeError("bd failed")

    updates = [
        {"update_id": 44, "message": {"from": {"id": 123}, "chat": {"id": 123}, "text": "/tasks"}}
    ]
    api = scripted_updates(updates)

    sent = api.sent
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(run_listener(app, tmp_path, api=api))

    assert len(sent) == 1
    assert sent[0][1] == "Could not fetch tasks."


def test_inbound_listener_tasks_rejected_sender_no_queue_call(tmp_path: Path) -> None:
    """/tasks from a non-allowlisted sender gets no reply and no queue access."""

    config = RuntimeConfig(telegram_allowed_ids="999")  # only 999 allowed
    app = MagicMock()
    app.state.fleet_state.config = config

    updates = [
        {"update_id": 45, "message": {"from": {"id": 111}, "chat": {"id": 111}, "text": "/tasks"}}
    ]
    api = scripted_updates(updates)

    sent = api.sent
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(run_listener(app, tmp_path, api=api))

    assert sent == [], "Rejected sender must get no reply"
    app.state.queue.list_in_progress.assert_not_called()
    app.state.queue.list_ready.assert_not_called()


def test_inbound_listener_task_command_sends_usage(tmp_path: Path) -> None:
    """Bare /task (no id) sends the combined usage reply."""

    config = RuntimeConfig(telegram_allowed_ids="123")
    app = MagicMock()
    app.state.fleet_state.config = config

    updates = [
        {"update_id": 41, "message": {"from": {"id": 123}, "chat": {"id": 123}, "text": "/task"}}
    ]
    api = scripted_updates(updates)

    sent = api.sent
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(run_listener(app, tmp_path, api=api))

    app.state.queue.create_task.assert_not_called()
    assert len(sent) == 1
    reply = sent[0][1]
    assert "/task <id>" in reply
    assert "/tasks" in reply
    assert "/new_task" in reply


def test_inbound_listener_tasks_not_confused_with_task(tmp_path: Path) -> None:
    """/tasks must NOT create a task; token dispatch prevents /task prefix match."""

    config = RuntimeConfig(telegram_allowed_ids="123")
    app = MagicMock()
    app.state.fleet_state.config = config

    updates = [
        {"update_id": 42, "message": {"from": {"id": 123}, "chat": {"id": 123}, "text": "/tasks"}}
    ]
    api = scripted_updates(updates)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(run_listener(app, tmp_path, api=api))

    app.state.queue.create_task.assert_not_called()


def test_inbound_listener_task_id_shows_details(tmp_path: Path) -> None:
    """/task <id> replies with the task's id, status, and title."""

    config = RuntimeConfig(telegram_allowed_ids="123")
    app = MagicMock()
    app.state.fleet_state.config = config

    fake_task = Task(
        id="fleet-xyz1", title="Fix the widget", description=None, status="in_progress"
    )
    app.state.queue.get.return_value = fake_task

    updates = [
        {
            "update_id": 50,
            "message": {"from": {"id": 123}, "chat": {"id": 123}, "text": "/task fleet-xyz1"},
        }
    ]
    api = scripted_updates(updates)

    sent = api.sent
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(run_listener(app, tmp_path, api=api))

    assert len(sent) == 1
    reply = sent[0][1]
    assert "fleet-xyz1" in reply
    assert "in_progress" in reply
    assert "Fix the widget" in reply


def test_inbound_listener_task_id_unknown_sends_hint(tmp_path: Path) -> None:
    """Unknown task id replies with 'No task <id>. To create a task use /new_task <title>'."""

    config = RuntimeConfig(telegram_allowed_ids="123")
    app = MagicMock()
    app.state.fleet_state.config = config
    app.state.queue.get.side_effect = RuntimeError("task not found")

    updates = [
        {
            "update_id": 51,
            "message": {"from": {"id": 123}, "chat": {"id": 123}, "text": "/task fleet-0000"},
        }
    ]
    api = scripted_updates(updates)

    sent = api.sent
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(run_listener(app, tmp_path, api=api))

    assert len(sent) == 1
    assert "No task fleet-0000" in sent[0][1]
    assert "/new_task" in sent[0][1]


def test_inbound_listener_task_id_rejected_sender_no_reply(tmp_path: Path) -> None:
    """/task <id> from a non-allowlisted sender gets no reply and no queue access."""

    config = RuntimeConfig(telegram_allowed_ids="999")
    app = MagicMock()
    app.state.fleet_state.config = config

    updates = [
        {
            "update_id": 53,
            "message": {"from": {"id": 111}, "chat": {"id": 111}, "text": "/task fleet-xyz1"},
        }
    ]
    api = scripted_updates(updates)

    sent = api.sent
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(run_listener(app, tmp_path, api=api))

    assert sent == [], "Rejected sender must get no reply"
    app.state.queue.get.assert_not_called()


def test_inbound_listener_offset_prevents_duplicate_on_restart(tmp_path: Path) -> None:
    """Saved offset from a previous run is passed to getUpdates on restart,
    preventing the same update from being processed twice."""

    config = RuntimeConfig(telegram_allowed_ids="123", telegram_default_cwd="")

    updates = [
        {
            "update_id": 7,
            "message": {
                "from": {"id": 123},
                "chat": {"id": 123},
                "text": "/new_task Title",
            },
        }
    ]
    api = scripted_updates(updates)

    fake_task = Task(id="fleet-xyz1", title="Title", description=None, status="open")
    offset_path = tmp_path / "offset"

    # --- First run: process the update and save offset ---
    app1 = MagicMock()
    app1.state.fleet_state.config = config
    app1.state.queue.create_task.return_value = fake_task

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(run_listener(app1, tmp_path, api=api))

    assert OffsetStore(offset_path).load() == 8
    assert app1.state.queue.create_task.call_count == 1

    # --- Second run: offset=8 should be passed to getUpdates ---
    app2 = MagicMock()
    app2.state.fleet_state.config = config
    api2 = FakeTelegramApi("tok", updates=[[], asyncio.CancelledError()])

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(run_listener(app2, tmp_path, api=api2))

    offsets = [params.get("offset") for _, params in api2.calls]
    assert offsets == [8, 8], "Second run must resume from saved offset=8"
    app2.state.queue.create_task.assert_not_called()
