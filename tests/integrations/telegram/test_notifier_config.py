"""Tests for telegram config round-trips and command parsing.

Units under test: ``integrations/telegram/commands.py`` (allowlist parsing,
``/new_task`` parsing, sender gating) and ``state/config_file.py`` for the
telegram settings persistence. Pure functions — no fakes needed.
"""

from __future__ import annotations

from pathlib import Path

from fleet.integrations.telegram.commands import (
    is_allowed,
    parse_allowed_ids,
    parse_new_task_command,
)
from fleet.state.config_file import load
from fleet.state.config_file import write as write_atomic


def test_telegram_chat_id_round_trips(tmp_path: Path) -> None:
    """telegram_chat_id persists through write_atomic and is readable via load."""
    cfg_path = tmp_path / "runtime.toml"
    load(cfg_path)

    result = write_atomic(cfg_path, {"telegram_chat_id": "my-channel-id"})
    assert result.telegram_chat_id == "my-channel-id"

    reloaded = load(cfg_path)
    assert reloaded.telegram_chat_id == "my-channel-id"


def test_telegram_chat_id_default_is_empty_string(tmp_path: Path) -> None:
    """telegram_chat_id defaults to empty string in a freshly created config."""
    cfg_path = tmp_path / "runtime.toml"
    config = load(cfg_path)
    assert config.telegram_chat_id == ""


# ---------------------------------------------------------------------------
# New config fields round-trip
# ---------------------------------------------------------------------------


def test_telegram_allowed_ids_default_is_empty_string(tmp_path: Path) -> None:
    config = load(tmp_path / "runtime.toml")
    assert config.telegram_allowed_ids == ""


def test_telegram_default_cwd_default_is_empty_string(tmp_path: Path) -> None:
    config = load(tmp_path / "runtime.toml")
    assert config.telegram_default_cwd == ""


def test_telegram_allowed_ids_round_trips(tmp_path: Path) -> None:
    cfg_path = tmp_path / "runtime.toml"
    load(cfg_path)
    result = write_atomic(cfg_path, {"telegram_allowed_ids": "111,222,333"})
    assert result.telegram_allowed_ids == "111,222,333"
    assert load(cfg_path).telegram_allowed_ids == "111,222,333"


def test_telegram_default_cwd_round_trips(tmp_path: Path) -> None:
    cfg_path = tmp_path / "runtime.toml"
    load(cfg_path)
    result = write_atomic(cfg_path, {"telegram_default_cwd": "/fleet_home/user/project"})
    assert result.telegram_default_cwd == "/fleet_home/user/project"
    assert load(cfg_path).telegram_default_cwd == "/fleet_home/user/project"


# ---------------------------------------------------------------------------
# _parse_allowed_ids
# ---------------------------------------------------------------------------


def test_parse_allowed_ids_empty_string() -> None:
    assert parse_allowed_ids("") == set()


def test_parse_allowed_ids_single() -> None:
    assert parse_allowed_ids("12345") == {"12345"}


def test_parse_allowed_ids_comma_separated() -> None:
    assert parse_allowed_ids("111, 222 , 333") == {"111", "222", "333"}


def test_parse_allowed_ids_ignores_empty_segments() -> None:
    assert parse_allowed_ids(",,,  ") == set()


# ---------------------------------------------------------------------------
# _is_allowed
# ---------------------------------------------------------------------------


def _make_update(from_id: str | None = None, chat_id: str | None = None) -> dict:
    msg: dict = {}
    if from_id is not None:
        msg["from"] = {"id": int(from_id)}
    if chat_id is not None:
        msg["chat"] = {"id": int(chat_id)}
    return {"update_id": 1, "message": msg}


def test_is_allowed_from_id_in_list() -> None:
    assert is_allowed(_make_update(from_id="123"), {"123"})


def test_is_allowed_chat_id_in_list() -> None:
    assert is_allowed(_make_update(chat_id="-100987"), {"-100987"})


def test_is_allowed_neither_in_list() -> None:
    assert not is_allowed(_make_update(from_id="111", chat_id="222"), {"999"})


def test_is_allowed_empty_allowlist() -> None:
    assert not is_allowed(_make_update(from_id="123", chat_id="123"), set())


def test_is_allowed_no_ids_in_update() -> None:
    assert not is_allowed({"update_id": 1, "message": {}}, {"123"})


# ---------------------------------------------------------------------------
# _parse_new_task_command
# ---------------------------------------------------------------------------


def test_parse_new_task_command_simple() -> None:
    assert parse_new_task_command("/new_task Fix the bug") == ("Fix the bug", None)


def test_parse_new_task_command_with_description() -> None:
    result = parse_new_task_command("/new_task Fix the bug\nDetails here\nMore info")
    assert result == ("Fix the bug", "Details here\nMore info")


def test_parse_new_task_command_not_a_new_task() -> None:
    assert parse_new_task_command("/start") is None
    assert parse_new_task_command("Hello world") is None
    assert parse_new_task_command("/task Fix the bug") is None


def test_parse_new_task_command_empty_title() -> None:
    assert parse_new_task_command("/new_task\n") is None
    assert parse_new_task_command("/new_task   ") is None


def test_parse_new_task_command_bot_name_variant() -> None:
    assert parse_new_task_command("/new_task@mybot Do something") == ("Do something", None)


def test_parse_new_task_command_newline_only_title() -> None:
    result = parse_new_task_command("/new_task Refactor module\n\nExtra notes")
    assert result is not None
    assert result[0] == "Refactor module"


def test_parse_new_task_command_title_on_next_line() -> None:
    """Title on the line after the command (no inline text) is accepted."""
    result = parse_new_task_command("/new_task\nMy title\ndetails here")
    assert result == ("My title", "details here")


def test_parse_new_task_command_title_on_next_line_no_desc() -> None:
    result = parse_new_task_command("/new_task\nJust the title")
    assert result == ("Just the title", None)


def test_parse_new_task_command_bare_no_text_returns_none() -> None:
    assert parse_new_task_command("/new_task") is None
    assert parse_new_task_command("/new_task\n\n  \n") is None


# ---------------------------------------------------------------------------
# Offset persistence
# ---------------------------------------------------------------------------
