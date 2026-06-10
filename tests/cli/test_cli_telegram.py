"""Tests for the `fleet telegram` CLI commands: setup, status, test."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from fleet.cli import app
from fleet.config import load as load_config
from fleet.config import write_atomic

runner = CliRunner()


def _patch_root(tmp_path: Path):
    return patch("fleet.cli._fleet_home", return_value=tmp_path)


def _init_config(tmp_path: Path, **kwargs) -> Path:
    path = tmp_path / "runtime.toml"
    load_config(path)
    if kwargs:
        write_atomic(path, kwargs)
    return path


def _make_update(
    update_id: int,
    chat_id: str,
    chat_type: str = "group",
    title: str = "TestGroup",
    from_id: int = 999,
    username: str = "testuser",
) -> dict:
    return {
        "update_id": update_id,
        "message": {
            "from": {"id": from_id, "username": username},
            "chat": {"id": int(chat_id), "type": chat_type, "title": title},
            "text": "hello",
        },
    }


# ---------------------------------------------------------------------------
# fleet telegram status
# ---------------------------------------------------------------------------


def test_telegram_status_no_token_exits_nonzero(tmp_path: Path) -> None:
    """Exit 1 when TELEGRAM_BOT_TOKEN is absent."""
    with _patch_root(tmp_path):
        result = runner.invoke(app, ["telegram", "status"], env={"TELEGRAM_BOT_TOKEN": ""})
    assert result.exit_code != 0
    assert "(not set)" in result.output


def test_telegram_status_full_token_never_in_stdout(tmp_path: Path) -> None:
    """The full token secret portion must never appear in stdout output."""
    token = "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi"
    with _patch_root(tmp_path):
        with patch("fleet.telegram.get_me", return_value={"username": "mybot"}):
            result = runner.invoke(
                app, ["telegram", "status"], env={"TELEGRAM_BOT_TOKEN": token}
            )
    assert token not in result.output
    # Masked form must appear
    assert "123456789...:***" in result.output


def test_telegram_status_invalid_token_exits_nonzero(tmp_path: Path) -> None:
    """Exit 1 when getMe raises (invalid token or network error)."""
    with _patch_root(tmp_path):
        with patch("fleet.telegram.get_me", side_effect=RuntimeError("Unauthorized")):
            result = runner.invoke(
                app, ["telegram", "status"], env={"TELEGRAM_BOT_TOKEN": "bad:token"}
            )
    assert result.exit_code != 0


def test_telegram_status_fully_configured_exits_zero(tmp_path: Path) -> None:
    """Exit 0 when token valid, chat_id and allowed_ids are both set."""
    _init_config(tmp_path, telegram_chat_id="-100123456", telegram_allowed_ids="111,222")
    with _patch_root(tmp_path):
        with patch("fleet.telegram.get_me", return_value={"username": "mybot"}):
            result = runner.invoke(
                app, ["telegram", "status"], env={"TELEGRAM_BOT_TOKEN": "123:tok"}
            )
    assert result.exit_code == 0
    assert "ok" in result.output


def test_telegram_status_missing_chat_id_exits_nonzero(tmp_path: Path) -> None:
    """Exit 1 when telegram_chat_id is absent (outbound not configured)."""
    _init_config(tmp_path, telegram_allowed_ids="111")
    with _patch_root(tmp_path):
        with patch("fleet.telegram.get_me", return_value={"username": "mybot"}):
            result = runner.invoke(
                app, ["telegram", "status"], env={"TELEGRAM_BOT_TOKEN": "123:tok"}
            )
    assert result.exit_code != 0


def test_telegram_status_missing_allowed_ids_exits_nonzero(tmp_path: Path) -> None:
    """Exit 1 when telegram_allowed_ids is absent (inbound not configured)."""
    _init_config(tmp_path, telegram_chat_id="-100123456")
    with _patch_root(tmp_path):
        with patch("fleet.telegram.get_me", return_value={"username": "mybot"}):
            result = runner.invoke(
                app, ["telegram", "status"], env={"TELEGRAM_BOT_TOKEN": "123:tok"}
            )
    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# fleet telegram test
# ---------------------------------------------------------------------------


def test_telegram_test_success_path(tmp_path: Path) -> None:
    """Exit 0 when token set, chat_id in config, and send succeeds."""
    _init_config(tmp_path, telegram_chat_id="-100abc")
    with _patch_root(tmp_path):
        with patch("fleet.telegram.send_message_raise") as mock_send:
            result = runner.invoke(
                app, ["telegram", "test"], env={"TELEGRAM_BOT_TOKEN": "123:tok"}
            )
    assert result.exit_code == 0, result.output
    mock_send.assert_called_once()
    assert "-100abc" in result.output


def test_telegram_test_no_token_exits_nonzero(tmp_path: Path) -> None:
    """Exit 1 when TELEGRAM_BOT_TOKEN is not set."""
    _init_config(tmp_path, telegram_chat_id="-100abc")
    with _patch_root(tmp_path):
        result = runner.invoke(app, ["telegram", "test"], env={"TELEGRAM_BOT_TOKEN": ""})
    assert result.exit_code != 0


def test_telegram_test_no_chat_id_exits_nonzero(tmp_path: Path) -> None:
    """Exit 1 when telegram_chat_id is not in config."""
    with _patch_root(tmp_path):
        result = runner.invoke(
            app, ["telegram", "test"], env={"TELEGRAM_BOT_TOKEN": "123:tok"}
        )
    assert result.exit_code != 0
    assert "telegram_chat_id" in result.output


def test_telegram_test_api_error_friendly_message(tmp_path: Path) -> None:
    """Exit 1 with a human-readable error, not a traceback, on Telegram API failure."""
    _init_config(tmp_path, telegram_chat_id="-100abc")
    with _patch_root(tmp_path):
        with patch(
            "fleet.telegram.send_message_raise",
            side_effect=RuntimeError("chat not found"),
        ):
            result = runner.invoke(
                app, ["telegram", "test"], env={"TELEGRAM_BOT_TOKEN": "123:tok"}
            )
    assert result.exit_code != 0
    assert "chat not found" in result.output
    # No Python traceback should appear
    assert "Traceback" not in result.output


# ---------------------------------------------------------------------------
# fleet telegram setup — non-interactive
# ---------------------------------------------------------------------------


def test_telegram_setup_writes_chat_id(tmp_path: Path) -> None:
    """--chat-id persists telegram_chat_id to runtime.toml."""
    with _patch_root(tmp_path):
        with patch("fleet.telegram.get_me", return_value={"username": "mybot"}):
            with patch("fleet.telegram.send_message_raise"):
                result = runner.invoke(
                    app,
                    ["telegram", "setup", "--chat-id", "-100xyz", "--yes"],
                    env={"TELEGRAM_BOT_TOKEN": "123:tok"},
                )
    assert result.exit_code == 0, result.output
    cfg = load_config(tmp_path / "runtime.toml")
    assert cfg.telegram_chat_id == "-100xyz"


def test_telegram_setup_writes_allowed_ids_and_default_cwd(tmp_path: Path) -> None:
    """--allowed-ids and --default-cwd persist their values to runtime.toml."""
    with _patch_root(tmp_path):
        with patch("fleet.telegram.get_me", return_value={"username": "mybot"}):
            with patch("fleet.telegram.send_message_raise"):
                result = runner.invoke(
                    app,
                    [
                        "telegram", "setup",
                        "--chat-id", "-100xyz",
                        "--allowed-ids", "111,222",
                        "--default-cwd", "/home/user/proj",
                        "--yes",
                    ],
                    env={"TELEGRAM_BOT_TOKEN": "123:tok"},
                )
    assert result.exit_code == 0, result.output
    cfg = load_config(tmp_path / "runtime.toml")
    assert cfg.telegram_allowed_ids == "111,222"
    assert cfg.telegram_default_cwd == "/home/user/proj"


def test_telegram_setup_no_test_skips_send(tmp_path: Path) -> None:
    """--no-test means send_message_raise is never called."""
    with _patch_root(tmp_path):
        with patch("fleet.telegram.get_me", return_value={"username": "mybot"}):
            with patch("fleet.telegram.send_message_raise") as mock_send:
                result = runner.invoke(
                    app,
                    ["telegram", "setup", "--chat-id", "-100xyz", "--no-test", "--yes"],
                    env={"TELEGRAM_BOT_TOKEN": "123:tok"},
                )
    assert result.exit_code == 0, result.output
    mock_send.assert_not_called()


def test_telegram_setup_missing_token_with_yes_fails_cleanly(tmp_path: Path) -> None:
    """Exit 1 with a helpful message when --yes is used without TELEGRAM_BOT_TOKEN."""
    with _patch_root(tmp_path):
        result = runner.invoke(
            app,
            ["telegram", "setup", "--chat-id", "-100xyz", "--yes"],
            env={"TELEGRAM_BOT_TOKEN": ""},
        )
    assert result.exit_code != 0
    assert "TELEGRAM_BOT_TOKEN" in result.output


def test_telegram_setup_token_not_written_to_runtime_toml(tmp_path: Path) -> None:
    """Token must never appear in runtime.toml, even on the full non-interactive path."""
    token = "987654321:SomeSecretTokenThatMustNotAppearInFile"
    with _patch_root(tmp_path):
        with patch("fleet.telegram.get_me", return_value={"username": "mybot"}):
            with patch("fleet.telegram.send_message_raise"):
                runner.invoke(
                    app,
                    [
                        "telegram", "setup",
                        "--chat-id", "-100xyz",
                        "--allowed-ids", "111",
                        "--default-cwd", "/proj",
                        "--yes",
                    ],
                    env={"TELEGRAM_BOT_TOKEN": token},
                )
    cfg_path = tmp_path / "runtime.toml"
    assert cfg_path.exists()
    content = cfg_path.read_text(encoding="utf-8")
    assert token not in content
    assert "SomeSecretToken" not in content


def test_telegram_setup_token_validated_via_get_me(tmp_path: Path) -> None:
    """getMe is called to validate the token; exit 1 on failure."""
    with _patch_root(tmp_path):
        with patch(
            "fleet.telegram.get_me", side_effect=RuntimeError("401 Unauthorized")
        ):
            result = runner.invoke(
                app,
                ["telegram", "setup", "--chat-id", "-100xyz", "--yes"],
                env={"TELEGRAM_BOT_TOKEN": "bad:token"},
            )
    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# fleet telegram setup — interactive chat discovery
# ---------------------------------------------------------------------------


def test_telegram_setup_chat_discovery_persists_selection(tmp_path: Path) -> None:
    """Chat discovered via getUpdates is written to runtime.toml when --yes auto-selects."""
    updates = [_make_update(10, "-100555", "channel", "My Channel")]
    with _patch_root(tmp_path):
        with patch("fleet.telegram.get_me", return_value={"username": "mybot"}):
            with patch("fleet.telegram.get_updates", return_value=updates):
                with patch("fleet.telegram.send_message_raise"):
                    result = runner.invoke(
                        app,
                        ["telegram", "setup", "--yes", "--no-test"],
                        env={"TELEGRAM_BOT_TOKEN": "123:tok"},
                    )
    assert result.exit_code == 0, result.output
    cfg = load_config(tmp_path / "runtime.toml")
    assert cfg.telegram_chat_id == "-100555"


def test_telegram_setup_chat_discovery_deduplicates_chats(tmp_path: Path) -> None:
    """Duplicate updates for the same chat appear only once in the discovered list."""
    updates = [
        _make_update(10, "-100111", "channel", "Channel A"),
        _make_update(11, "-100111", "channel", "Channel A"),  # same chat, different update_id
        _make_update(12, "-100222", "group", "Group B"),
    ]
    with _patch_root(tmp_path):
        with patch("fleet.telegram.get_me", return_value={"username": "mybot"}):
            with patch("fleet.telegram.get_updates", return_value=updates):
                with patch("fleet.telegram.send_message_raise"):
                    result = runner.invoke(
                        app,
                        ["telegram", "setup", "--yes", "--no-test"],
                        env={"TELEGRAM_BOT_TOKEN": "123:tok"},
                    )
    assert result.exit_code == 0, result.output
    # Both distinct chats appear in output
    assert "Channel A" in result.output
    assert "Group B" in result.output
    # Chat list has exactly 2 entries, not 3
    assert "2. " in result.output
    assert "3. " not in result.output


def test_telegram_setup_chat_discovery_no_messages_exits_nonzero(tmp_path: Path) -> None:
    """Exit 1 when polling returns no updates (no chat found)."""
    with _patch_root(tmp_path):
        with patch("fleet.telegram.get_me", return_value={"username": "mybot"}):
            with patch("fleet.telegram.get_updates", return_value=[]):
                result = runner.invoke(
                    app,
                    ["telegram", "setup", "--yes"],
                    env={"TELEGRAM_BOT_TOKEN": "123:tok"},
                )
    assert result.exit_code != 0
    assert "No messages" in result.output or "no messages" in result.output.lower()


def test_telegram_setup_chat_discovery_network_error_exits_nonzero(tmp_path: Path) -> None:
    """Exit 1 with a friendly message when getUpdates raises a network error."""
    with _patch_root(tmp_path):
        with patch("fleet.telegram.get_me", return_value={"username": "mybot"}):
            with patch(
                "fleet.telegram.get_updates",
                side_effect=RuntimeError("connection timeout"),
            ):
                result = runner.invoke(
                    app,
                    ["telegram", "setup", "--yes"],
                    env={"TELEGRAM_BOT_TOKEN": "123:tok"},
                )
    assert result.exit_code != 0
    assert "Traceback" not in result.output
