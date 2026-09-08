"""`fleet telegram` — status/test for the Telegram integration.

Thin commands: they compute (read env/config, validate the token) and print
through ``cli/render.py``. The setup wizard lives in
``cli/telegram_setup.py``; polling/validation/config-writing lives in
``fleet.integrations.telegram.setup``.
"""

from __future__ import annotations

import os
from typing import Annotated

import typer

from fleet.cli import bootstrap, render
from fleet.cli.render import TelegramStatus
from fleet.cli.telegram_setup import register as register_setup
from fleet.core.config import RuntimeConfig
from fleet.integrations.telegram import setup as telegram_setup


def _probe_status(token: str, cfg: RuntimeConfig) -> TelegramStatus:
    """Validate the token and pack every status fact render needs."""
    username: str | None = None
    error: str | None = None
    if token:
        try:
            username = telegram_setup.validate_token(token).get("username", "?")
        except Exception as exc:
            error = str(exc)
    return TelegramStatus(
        bot_username=username,
        bot_error=error,
        chat_id=cfg.telegram_chat_id,
        allowed_ids=cfg.telegram_allowed_ids,
        default_cwd=cfg.telegram_default_cwd,
    )


def register(app: typer.Typer) -> None:
    """Build the ``telegram`` subgroup: status, test, and the setup wizard."""
    telegram_app = typer.Typer(no_args_is_help=True, help="Telegram integration diagnostics.")
    app.add_typer(telegram_app, name="telegram", help="Telegram integration diagnostics.")

    @telegram_app.command("status")
    def telegram_status() -> None:
        """Show Telegram configuration and connectivity status.

        Exits 0 when fully configured (token valid, chat id and allowed ids set),
        exits 1 otherwise — suitable for scripting.
        """
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        status = _probe_status(token, bootstrap.config(bootstrap.home()))
        render.print_telegram_status(status, render.mask_token(token) if token else "(not set)")
        if not render.telegram_verdict_ok(status):
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
        cfg = bootstrap.config(bootstrap.home())
        if not cfg.telegram_chat_id:
            typer.echo(
                "Error: telegram_chat_id is not configured. "
                "Run `fleet config set telegram_chat_id=<id>`.",
                err=True,
            )
            raise typer.Exit(1)
        try:
            telegram_setup.send_test_message(token, cfg.telegram_chat_id, message)
        except Exception as exc:
            typer.echo(f"Error: {exc}", err=True)
            raise typer.Exit(1) from exc
        render.print_test_sent(cfg.telegram_chat_id)

    register_setup(telegram_app)
