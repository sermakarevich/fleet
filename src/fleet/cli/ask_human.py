"""`fleet ask-human` — vendored human-in-the-loop question broker."""

from __future__ import annotations

import subprocess
import sys
from typing import Annotated

import typer

_ASK_HUMAN_HELP = "ask_human MCP server — the backend of the fleet chat tab."


def register(app: typer.Typer) -> None:
    ask_human_app = typer.Typer(no_args_is_help=True, help=_ASK_HUMAN_HELP)
    app.add_typer(ask_human_app, name="ask-human", help=_ASK_HUMAN_HELP)

    @ask_human_app.command("serve")
    def ask_human_serve() -> None:
        """Run the ask_human MCP server on stdio (the target for `claude mcp add`)."""
        from fleet.integrations.ask_human.server import main as _serve_main

        _serve_main()

    @ask_human_app.command("install")
    def ask_human_install(
        scope: Annotated[
            str,
            typer.Option("--scope", help="Claude Code MCP scope: user, project, or local."),
        ] = "user",
    ) -> None:
        """Register the vendored MCP server with Claude Code (`claude mcp add ask_human`)."""
        import shutil

        claude = shutil.which("claude")
        if not claude:
            typer.echo("Error: 'claude' CLI not found in PATH.", err=True)
            raise typer.Exit(1)
        fleet_bin = shutil.which("fleet") or sys.argv[0]

        subprocess.run(
            [claude, "mcp", "remove", "ask_human", "--scope", scope],
            capture_output=True,
            text=True,
        )
        result = subprocess.run(
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
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            typer.echo(f"Error: claude mcp add failed: {result.stderr.strip()}", err=True)
            raise typer.Exit(1)
        typer.echo(
            f"Registered MCP server 'ask_human' ({scope} scope) -> {fleet_bin} ask-human serve"
        )
        typer.echo("Verify with: claude mcp list")
