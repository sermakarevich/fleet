"""`fleet telegram setup` — guided wizard to configure the Telegram integration.

Called by ``cli/telegram.py`` after it builds the ``telegram`` subgroup.
Every prompt, confirmation, and printed message lives here; the actual
polling/validation/config-writing logic lives in
``fleet.integrations.telegram.setup``. The wizard runs in four phases —
token, chat discovery, inbound, test message — each a small helper; the
command itself only orchestrates. The final summary prints through
``cli/render.py``.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, Any

import typer

from fleet.cli import bootstrap, render
from fleet.integrations.telegram import setup as telegram_setup


def _wizard_token(yes: bool) -> tuple[str, str]:
    """Read the bot token (env or prompt) and validate it; return (token, username)."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        if yes:
            typer.echo(
                "Error: TELEGRAM_BOT_TOKEN is not set. Export it before running with --yes.",
                err=True,
            )
            raise typer.Exit(1)
        token = typer.prompt("Bot token", hide_input=True)
    typer.echo("Validating token... ", nl=False)
    try:
        bot = telegram_setup.validate_token(token)
    except Exception as exc:
        typer.echo(f"failed\nError: {exc}", err=True)
        raise typer.Exit(1) from exc
    bot_username = bot.get("username", "?")
    typer.echo(f"ok — @{bot_username}")
    if not os.environ.get("TELEGRAM_BOT_TOKEN"):
        typer.echo(
            "\nAdd this to your shell profile "
            "(token is never stored in runtime.toml):\n"
            f"  export TELEGRAM_BOT_TOKEN={token}\n"
        )
    return token, bot_username


def _choose_chat(chat_list: list[dict], yes: bool) -> dict:
    """Print discovered chats and return the chosen one."""
    typer.echo("\nChats found:")
    for i, c in enumerate(chat_list, 1):
        typer.echo(f"  {i}. [{c['type']}] {c['title']}  (id: {c['id']})")
    if len(chat_list) == 1 or yes:
        return chat_list[0]
    raw = typer.prompt("Choose a number", default="1")
    try:
        idx = int(raw) - 1
        if not 0 <= idx < len(chat_list):
            raise ValueError
        return chat_list[idx]
    except ValueError:
        typer.echo("Invalid choice.", err=True)
        raise typer.Exit(1) from None


def _wizard_chat_id(
    token: str, bot_username: str, chat_id: str | None, yes: bool
) -> tuple[str, Any]:
    """Resolve the chat id by discovery polling, or take the --chat-id flag."""
    if chat_id is not None:
        return chat_id, None
    typer.echo("\nStep 2 of 3 — Discover chat/channel ID")
    typer.echo(f"  • Add @{bot_username} as an admin to your channel or group")
    typer.echo("  • Post any message in that chat")
    if not yes:
        input("  • Press Enter here when ready... ")
    typer.echo("Polling for messages", nl=False)
    try:
        chat_list, offset = telegram_setup.discover_chats(token)
    except Exception as exc:
        typer.echo(f"\nNetwork error while polling: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo()  # newline after dots
    if not chat_list:
        typer.echo(
            "No messages received. Make sure the bot is in the chat and a message was sent.",
            err=True,
        )
        raise typer.Exit(1)
    chosen = _choose_chat(chat_list, yes)
    typer.echo(f"Selected: [{chosen['type']}] {chosen['title']}  (id: {chosen['id']})")
    return chosen["id"], offset


def _write_chat_id(path: Path, written_keys: dict[str, str], chosen_chat_id: str) -> None:
    """Persist the chat id, recording it in *written_keys*; exit 1 on failure."""
    try:
        telegram_setup.write_chat_id(path, chosen_chat_id)
        written_keys["telegram_chat_id"] = chosen_chat_id
    except Exception as exc:
        typer.echo(f"Error writing config: {exc}", err=True)
        raise typer.Exit(1) from exc


def _capture_allowed_ids(token: str, bot_username: str, offset: Any) -> str | None:
    """Poll for the operator's user id; None when no user message arrived."""
    typer.echo("\nStep 3 of 3 — Capture your Telegram user ID")
    typer.echo(f"  • DM /start to @{bot_username} from your Telegram account")
    input("  • Press Enter here when done... ")
    typer.echo("Capturing user ID", nl=False)
    try:
        seen_users, _ = telegram_setup.discover_users(token, offset)
    except Exception as exc:
        typer.echo(f"\nNetwork error while polling: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo()
    if not seen_users:
        typer.echo("Warning: no user messages found — skipping inbound setup.")
        return None
    typer.echo("Users found:")
    for fid, uname in seen_users.items():
        typer.echo(f"  {fid}: @{uname}")
    return ",".join(seen_users.keys())


def _wizard_inbound(
    token: str,
    bot_username: str,
    allowed_ids: str | None,
    default_cwd: str | None,
    yes: bool,
    offset: Any,
) -> tuple[str, str] | None:
    """Capture inbound task-creation config; None when inbound stays off."""
    if allowed_ids is not None:
        enable_inbound = True
        allowed_ids_value = allowed_ids
    elif yes:
        return None
    else:
        enable_inbound = typer.confirm(
            "\nEnable inbound task creation from Telegram?", default=False
        )
        allowed_ids_value = ""
    if enable_inbound and allowed_ids is None:
        captured = _capture_allowed_ids(token, bot_username, offset)
        if captured is None:
            return None
        allowed_ids_value = captured
    if not enable_inbound:
        return None
    if default_cwd is None:
        default_cwd_value = typer.prompt(
            "Default working directory for inbound tasks", default=os.getcwd()
        )
    else:
        default_cwd_value = default_cwd
    return allowed_ids_value, default_cwd_value


def _write_inbound_config(
    path: Path, written_keys: dict[str, str], allowed_ids_value: str, default_cwd_value: str
) -> None:
    """Persist inbound config, recording keys in *written_keys*; exit 1 on failure."""
    try:
        telegram_setup.write_inbound_config(path, allowed_ids_value, default_cwd_value)
        written_keys["telegram_allowed_ids"] = allowed_ids_value
        written_keys["telegram_default_cwd"] = default_cwd_value
    except Exception as exc:
        typer.echo(f"Error writing config: {exc}", err=True)
        raise typer.Exit(1) from exc


def _send_test_message(token: str, chosen_chat_id: str) -> None:
    """Send the post-setup test message; failures warn, never fail the wizard."""
    typer.echo("\nSending test message... ", nl=False)
    try:
        telegram_setup.send_test_message(token, chosen_chat_id, "fleet: telegram configured")
        typer.echo("ok")
    except Exception as exc:
        typer.echo(f"warning: {exc}")


def register(telegram_app: typer.Typer) -> None:
    """Add the `setup` wizard command to the ``telegram`` subgroup."""

    @telegram_app.command("setup")
    def telegram_setup_cmd(
        chat_id: Annotated[
            str | None,
            typer.Option(
                "--chat-id",
                help="Chat/channel ID to use directly (skip discovery polling).",
            ),
        ] = None,
        allowed_ids: Annotated[
            str | None,
            typer.Option(
                "--allowed-ids",
                help=(
                    "Comma-separated Telegram user IDs allowed for inbound tasks (skip discovery)."
                ),
            ),
        ] = None,
        default_cwd: Annotated[
            str | None,
            typer.Option("--default-cwd", help="Default working directory for inbound tasks."),
        ] = None,
        no_test: Annotated[
            bool, typer.Option("--no-test", help="Skip sending a test message after setup.")
        ] = False,
        yes: Annotated[
            bool,
            typer.Option(
                "--yes",
                "-y",
                help="Non-interactive: skip 'Press Enter' pauses; auto-select first found chat.",
            ),
        ] = False,
    ) -> None:
        """Guided wizard to configure the Telegram integration.

        Steps: (1) validate bot token, (2) discover chat/channel ID by polling
        for messages, (3) optionally enable inbound /task creation, (4) send a
        test message and print a summary of every key written.

        Token is NEVER written to runtime.toml — the wizard prints the exact
        export line to add to your shell profile instead.

        Pass --chat-id / --allowed-ids / --default-cwd to skip the corresponding
        interactive steps for non-interactive / scripted use.
        """
        path = bootstrap.fleet_home() / "runtime.toml"
        written_keys: dict[str, str] = {}
        token, bot_username = _wizard_token(yes)
        chosen_chat_id, offset = _wizard_chat_id(token, bot_username, chat_id, yes)
        _write_chat_id(path, written_keys, chosen_chat_id)
        inbound = _wizard_inbound(token, bot_username, allowed_ids, default_cwd, yes, offset)
        if inbound is not None:
            _write_inbound_config(path, written_keys, inbound[0], inbound[1])
        if not no_test:
            _send_test_message(token, chosen_chat_id)
        render.print_setup_summary(path, written_keys)
