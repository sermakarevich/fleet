"""`fleet ask-human` — vendored human-in-the-loop question broker."""

from __future__ import annotations

import shutil
import sys
from typing import Annotated

import typer

from fleet.cli import subproc
from fleet.cli.errors import ExitCode, fail
from fleet.core.errors import SubprocessTimeout
from fleet.integrations.ask_human.server import main

_ASK_HUMAN_HELP = "ask_human MCP server — the backend of the fleet chat tab."

_ASK_HUMAN_EPILOG = "Examples:\n\n  fleet ask-human install --scope user\n  fleet ask-human serve"


def register(app: typer.Typer) -> None:
    ask_human_app = typer.Typer(
        no_args_is_help=True, help=_ASK_HUMAN_HELP, epilog=_ASK_HUMAN_EPILOG
    )
    app.add_typer(ask_human_app, name="ask-human", help=_ASK_HUMAN_HELP)

    @ask_human_app.command("serve")
    def ask_human_serve() -> None:
        """Run the ask_human MCP server on stdio (the target for `claude mcp add`)."""

        main()

    @ask_human_app.command("install")
    def ask_human_install(
        scope: Annotated[
            str,
            typer.Option("--scope", help="Claude Code MCP scope: user, project, or local."),
        ] = "user",
    ) -> None:
        """Register the vendored MCP server with Claude Code (`claude mcp add ask_human`)."""

        claude = shutil.which("claude")
        if not claude:
            fail("'claude' CLI not found in PATH.", ExitCode.NOT_FOUND)
        fleet_bin = shutil.which("fleet") or sys.argv[0]

        try:
            subproc.run(
                [claude, "mcp", "remove", "ask_human", "--scope", scope],
                capture=True,
            )
            result = subproc.run(
                [
                    claude,
                    "mcp",
                    "add",
                    "ask_human",
                    "--scope",
                    scope,
                    "--",
                    fleet_bin,
                    "ask-human",
                    "serve",
                ],
                capture=True,
            )
        except SubprocessTimeout as exc:
            fail(f"{' '.join(exc.argv)} timed out.", ExitCode.BACKEND)
        if result.returncode != 0:
            fail(f"claude mcp add failed: {result.stderr.strip()}", ExitCode.BACKEND)
        typer.echo(
            f"Registered MCP server 'ask_human' ({scope} scope) -> {fleet_bin} ask-human serve"
        )
        typer.echo("Verify with: claude mcp list")
