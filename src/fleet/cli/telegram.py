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
from fleet.cli.errors import ExitCode, fail
from fleet.cli.render import TelegramStatus
from fleet.cli.telegram_setup import register as register_setup
from fleet.core.config import RuntimeConfig
from fleet.integrations.telegram import setup as telegram_setup


def _probe_status(token: str, config: RuntimeConfig) -> TelegramStatus:
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
        chat_id=config.telegram_chat_id,
        allowed_ids=config.telegram_allowed_ids,
        default_cwd=config.telegram_default_cwd,
    )


def register(app: typer.Typer) -> None:
    """Build the ``telegram`` subgroup: status, test, and the setup wizard."""
    telegram_app = typer.Typer(
        no_args_is_help=True,
        help="Telegram integration diagnostics.",
        epilog=(
            "Examples:\n\n"
            "  fleet telegram status\n"
            '  fleet telegram test --message "hello from fleet"\n'
            "  fleet telegram setup --chat-id -1001234567890 --yes"
        ),
    )
    app.add_typer(telegram_app, name="telegram", help="Telegram integration diagnostics.")

    @telegram_app.command("status")
    def telegram_status() -> None:
        """Show Telegram configuration and connectivity status.

        Exits 0 when fully configured (token valid, chat id and allowed ids set),
        exits 1 otherwise — suitable for scripting.
        """
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        status = _probe_status(token, bootstrap.config(bootstrap.fleet_home()))
        render.print_telegram_status(status, render.mask_token(token) if token else "(not set)")
        if not render.telegram_verdict_ok(status):
            raise typer.Exit(int(ExitCode.ERROR))

    @telegram_app.command("test")
    def telegram_test(
        message: Annotated[str, typer.Option("--message", help="Text to send.")] = (
            "fleet: test message"
        ),
    ) -> None:
        """Send a test message to the configured Telegram chat."""
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        if not token:
            fail("TELEGRAM_BOT_TOKEN is not set.", ExitCode.ERROR)
        config = bootstrap.config(bootstrap.fleet_home())
        if not config.telegram_chat_id:
            fail(
                "telegram_chat_id is not configured. Run `fleet config set telegram_chat_id=<id>`.",
                ExitCode.USAGE,
            )
        try:
            telegram_setup.send_test_message(token, config.telegram_chat_id, message)
        except Exception as exc:
            fail(str(exc), ExitCode.BACKEND)
        render.print_test_sent(config.telegram_chat_id)

    register_setup(telegram_app)
