"""`fleet config` — show/set runtime configuration."""

from __future__ import annotations

from dataclasses import fields as dc_fields
from typing import Annotated

import typer

from fleet.core.config import load as load_config
from fleet.core.config import write_atomic
from fleet.state.paths import fleet_home


def register(app: typer.Typer) -> None:
    config_app = typer.Typer(no_args_is_help=True)
    app.add_typer(config_app, name="config", help="Manage runtime configuration.")

    @config_app.command("show")
    def config_show(
        raw: Annotated[bool, typer.Option("--raw", help="Print raw TOML bytes.")] = False,
    ) -> None:
        """Show the current runtime configuration."""
        path = fleet_home() / "runtime.toml"
        if raw:
            if path.exists():
                typer.echo(path.read_text(encoding="utf-8"), nl=False)
            else:
                typer.echo("# No config file found (using defaults)")
            return
        cfg = load_config(path)
        typer.echo(f"{'key':<38} value")
        typer.echo("-" * 55)
        for f in dc_fields(cfg):
            typer.echo(f"{f.name:<38} {getattr(cfg, f.name)!s}")

    @config_app.command("set")
    def config_set(
        pairs: Annotated[
            list[str],
            typer.Argument(metavar="key=value", help="One or more key=value pairs."),
        ],
    ) -> None:
        """Update one or more runtime config keys atomically."""
        updates: dict[str, str] = {}
        for pair in pairs:
            if "=" not in pair:
                typer.echo(
                    f"Error: invalid argument {pair!r} — expected key=value format.",
                    err=True,
                )
                raise typer.Exit(1)
            k, _, v = pair.partition("=")
            updates[k.strip()] = v.strip()

        path = fleet_home() / "runtime.toml"
        try:
            new_cfg = write_atomic(path, updates)
        except ValueError as exc:
            typer.echo(f"Error: {exc}", err=True)
            raise typer.Exit(1)

        typer.echo(f"{'key':<38} value")
        typer.echo("-" * 55)
        for f in dc_fields(new_cfg):
            typer.echo(f"{f.name:<38} {getattr(new_cfg, f.name)!s}")
