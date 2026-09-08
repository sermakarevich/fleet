"""`fleet telegram` — status/test/setup for the Telegram integration.

Every prompt, confirmation, and printed message lives here; the actual
polling/validation/config-writing logic lives in
`fleet.integrations.telegram.setup`.
"""

from __future__ import annotations

import os
from typing import Annotated

import typer

from fleet.core.config import load as load_config
from fleet.integrations.telegram import setup as telegram_setup
from fleet.state.paths import fleet_home

_TELE_W = 26  # key column width for telegram output
_TOKEN_PREFIX_LEN = 6  # how many leading token chars may appear in masked output


def _mask_token(token: str) -> str:
    """Return '12345...:***' — never exposes the secret part of the token."""
    if ":" not in token:
        return (token[:_TOKEN_PREFIX_LEN] + "...") if len(token) > _TOKEN_PREFIX_LEN else "***"
    bot_id, _ = token.split(":", 1)
    return f"{bot_id}...:***"


def register(app: typer.Typer) -> None:  # noqa: PLR0915  # ADR 0006 bead 12
    telegram_app = typer.Typer(no_args_is_help=True, help="Telegram integration diagnostics.")
    app.add_typer(telegram_app, name="telegram", help="Telegram integration diagnostics.")

    @telegram_app.command("status")
    def telegram_status() -> None:
        """Show Telegram configuration and connectivity status.

        Exits 0 when fully configured (token valid, chat id and allowed ids set),
        exits 1 otherwise — suitable for scripting.
        """
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        cfg = load_config(fleet_home() / "runtime.toml")

        typer.echo(
            f"{'TELEGRAM_BOT_TOKEN':<{_TELE_W}} {_mask_token(token) if token else '(not set)'}"
        )

        bot_ok = False
        if token:
            try:
                info = telegram_setup.validate_token(token)
                username = info.get("username", "?")
                typer.echo(f"{'bot':<{_TELE_W}} @{username}")
                bot_ok = True
            except Exception as exc:
                typer.echo(f"{'bot':<{_TELE_W}} token invalid/unreachable ({exc})")
        else:
            typer.echo(f"{'bot':<{_TELE_W}} (token not set)")

        typer.echo("")
        typer.echo(f"{'telegram_chat_id':<{_TELE_W}} {cfg.telegram_chat_id or '(not set)'}")
        typer.echo(f"{'telegram_allowed_ids':<{_TELE_W}} {cfg.telegram_allowed_ids or '(not set)'}")
        typer.echo(f"{'telegram_default_cwd':<{_TELE_W}} {cfg.telegram_default_cwd or '(not set)'}")

        outbound_ok = bot_ok and bool(cfg.telegram_chat_id)
        inbound_ok = bot_ok and bool(cfg.telegram_allowed_ids)

        typer.echo("")
        out_verdict = (
            "ok" if outbound_ok else "NOT configured — need valid token + telegram_chat_id"
        )
        in_verdict = (
            "ok" if inbound_ok else "NOT configured — need valid token + telegram_allowed_ids"
        )
        typer.echo(f"{'outbound notifications':<{_TELE_W}} {out_verdict}")
        typer.echo(f"{'inbound /task creation':<{_TELE_W}} {in_verdict}")

        if not (outbound_ok and inbound_ok):
            raise typer.Exit(1)

    @telegram_app.command("test")
    def telegram_test(
        message: Annotated[str, typer.Option("--message", help="Text to send.")] = (
            "fleet: test message"
        ),
    ) -> None:
        """Send a test message to the configured Telegram chat."""
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        if not token:
            typer.echo("Error: TELEGRAM_BOT_TOKEN is not set.", err=True)
            raise typer.Exit(1)

        cfg = load_config(fleet_home() / "runtime.toml")
        if not cfg.telegram_chat_id:
            typer.echo(
                "Error: telegram_chat_id is not configured. "
                "Run `fleet config set telegram_chat_id=<id>`.",
                err=True,
            )
            raise typer.Exit(1)

        try:
            telegram_setup.send_test_message(token, cfg.telegram_chat_id, message)
            typer.echo(f"Message sent to {cfg.telegram_chat_id}.")
        except Exception as exc:
            typer.echo(f"Error: {exc}", err=True)
            raise typer.Exit(1) from exc

    @telegram_app.command("setup")
    def telegram_setup_cmd(  # noqa: PLR0912, PLR0915  # ADR 0006 bead 12
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
        path = fleet_home() / "runtime.toml"
        written_keys: dict[str, str] = {}

        # ── (a) Token ──────────────────────────────────────────────────────────
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

        # ── (b) Chat-id discovery ──────────────────────────────────────────────
        if chat_id is None:
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
                    "No messages received. "
                    "Make sure the bot is in the chat and a message was sent.",
                    err=True,
                )
                raise typer.Exit(1)

            typer.echo("\nChats found:")
            for i, c in enumerate(chat_list, 1):
                typer.echo(f"  {i}. [{c['type']}] {c['title']}  (id: {c['id']})")

            if len(chat_list) == 1 or yes:
                chosen = chat_list[0]
            else:
                raw = typer.prompt("Choose a number", default="1")
                try:
                    idx = int(raw) - 1
                    if not 0 <= idx < len(chat_list):
                        raise ValueError
                    chosen = chat_list[idx]
                except ValueError:
                    typer.echo("Invalid choice.", err=True)
                    raise typer.Exit(1) from None

            chosen_chat_id = chosen["id"]
            typer.echo(f"Selected: [{chosen['type']}] {chosen['title']}  (id: {chosen_chat_id})")
        else:
            chosen_chat_id = chat_id
            offset = None

        try:
            telegram_setup.write_chat_id(path, chosen_chat_id)
            written_keys["telegram_chat_id"] = chosen_chat_id
        except Exception as exc:
            typer.echo(f"Error writing config: {exc}", err=True)
            raise typer.Exit(1) from exc

        # ── (c) Inbound (optional) ──────────────────────────────────────────────
        allowed_ids_value: str = ""
        if allowed_ids is not None:
            enable_inbound = True
            allowed_ids_value = allowed_ids
        elif yes:
            enable_inbound = False
        else:
            enable_inbound = typer.confirm(
                "\nEnable inbound task creation from Telegram?", default=False
            )

        if enable_inbound and allowed_ids is None:
            typer.echo("\nStep 3 of 3 — Capture your Telegram user ID")
            typer.echo(f"  • DM /start to @{bot_username} from your Telegram account")
            if not yes:
                input("  • Press Enter here when done... ")

            typer.echo("Capturing user ID", nl=False)
            try:
                seen_users, offset = telegram_setup.discover_users(token, offset)
            except Exception as exc:
                typer.echo(f"\nNetwork error while polling: {exc}", err=True)
                raise typer.Exit(1) from exc
            typer.echo()

            if not seen_users:
                typer.echo("Warning: no user messages found — skipping inbound setup.")
                enable_inbound = False
            else:
                typer.echo("Users found:")
                for fid, uname in seen_users.items():
                    typer.echo(f"  {fid}: @{uname}")
                allowed_ids_value = ",".join(seen_users.keys())

        if enable_inbound:
            if default_cwd is None:
                default_cwd_value = typer.prompt(
                    "Default working directory for inbound tasks", default=os.getcwd()
                )
            else:
                default_cwd_value = default_cwd

            try:
                telegram_setup.write_inbound_config(path, allowed_ids_value, default_cwd_value)
                written_keys["telegram_allowed_ids"] = allowed_ids_value
                written_keys["telegram_default_cwd"] = default_cwd_value
            except Exception as exc:
                typer.echo(f"Error writing config: {exc}", err=True)
                raise typer.Exit(1) from exc

        # ── (d) Finish — test message ──────────────────────────────────────────
        if not no_test:
            typer.echo("\nSending test message... ", nl=False)
            try:
                telegram_setup.send_test_message(
                    token, chosen_chat_id, "fleet: telegram configured"
                )
                typer.echo("ok")
            except Exception as exc:
                typer.echo(f"warning: {exc}")

        # Summary
        typer.echo(f"\nSetup complete. Written to {path}:")
        if written_keys:
            for k, v in written_keys.items():
                typer.echo(f"  {k} = {v}")
        else:
            typer.echo("  (nothing written — all values were provided via flags)")
