"""`fleet config` — show/set runtime configuration."""

from __future__ import annotations

from dataclasses import fields as dc_fields
from pathlib import Path
from typing import Annotated

import typer

from fleet.cli.errors import ExitCode, fail
from fleet.coders import get_coder
from fleet.core.config import render_settings_table, render_toml_header
from fleet.core.errors import ConfigError
from fleet.core.limits import render_tunables_table
from fleet.state.config_file import load as load_config
from fleet.state.config_file import write as write_config
from fleet.state.paths import fleet_home


def repo_paths() -> dict[str, Path]:
    """Generated config-doc paths rooted at the checkout (editable install)."""
    root = Path(__file__).resolve().parents[3]
    return {
        "config_doc": root / "docs" / "CONFIG.md",
        "toml_header": root / "src" / "fleet" / "templates" / "runtime.toml.header",
    }


def splice_region(text: str, name: str, body: str) -> str:
    """Replace a BEGIN/END GENERATED region with *body* (markers preserved)."""
    begin = f"<!-- BEGIN GENERATED:{name} -->"
    end = f"<!-- END GENERATED:{name} -->"
    head, sep, rest = text.partition(begin)
    if not sep:
        raise ConfigError(f"CONFIG.md is missing region marker {begin}")
    _, sep2, tail = rest.partition(end)
    if not sep2:
        raise ConfigError(f"CONFIG.md is missing region marker {end}")
    return f"{head}{begin}\n{body.rstrip()}\n{sep2}{tail}"


def expected_doc_files() -> dict[str, str]:
    """Generated file contents keyed by path: CONFIG.md regions spliced in."""
    paths = repo_paths()
    current = paths["config_doc"].read_text(encoding="utf-8")
    updated = splice_region(current, "SETTINGS", render_settings_table())
    updated = splice_region(updated, "TUNABLES", render_tunables_table())
    return {
        str(paths["config_doc"]): updated,
        str(paths["toml_header"]): render_toml_header(),
    }


def doc_drift() -> dict[str, str]:
    """Generated files whose on-disk bytes differ; empty means in sync."""
    drifted = {}
    for path_str, expected in expected_doc_files().items():
        path = Path(path_str)
        if not path.exists() or path.read_text(encoding="utf-8") != expected:
            drifted[path_str] = expected
    return drifted


def register(app: typer.Typer) -> None:
    config_app = typer.Typer(
        no_args_is_help=True,
        epilog=(
            "Examples:\n\n"
            "  fleet config show\n"
            "  fleet config set model=sonnet\n"
            "  fleet config set serve_port=7890 serve_host=127.0.0.1\n"
            "  fleet config docs\n"
        ),
    )
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
        config = load_config(path)
        typer.echo(f"{'key':<38} value")
        typer.echo("-" * 55)
        for f in dc_fields(config):
            typer.echo(f"{f.name:<38} {getattr(config, f.name)!s}")

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
                fail(
                    f"invalid argument {pair!r} — expected key=value format.",
                    ExitCode.USAGE,
                )
            k, _, v = pair.partition("=")
            updates[k.strip()] = v.strip()

        path = fleet_home() / "runtime.toml"
        if "coder" in updates:
            try:
                get_coder(updates["coder"])
            except ValueError as exc:
                fail(str(exc), ExitCode.USAGE)
        try:
            new_cfg = write_config(path, updates)
        except ValueError as exc:
            fail(str(exc), ExitCode.USAGE)

        typer.echo(f"{'key':<38} value")
        typer.echo("-" * 55)
        for f in dc_fields(new_cfg):
            typer.echo(f"{f.name:<38} {getattr(new_cfg, f.name)!s}")

    @config_app.command("docs")
    def config_docs(
        write: Annotated[
            bool,
            typer.Option("--write", help="Rewrite docs/CONFIG.md and runtime.toml.header."),
        ] = False,
        check: Annotated[
            bool,
            typer.Option("--check", help="Exit 1 when generated docs drift."),
        ] = False,
    ) -> None:
        """Print the settings table, or --write/--check the generated docs."""
        if write and check:
            fail("--write and --check are mutually exclusive.", ExitCode.USAGE)
        if write:
            for path_str, expected in expected_doc_files().items():
                Path(path_str).write_text(expected, encoding="utf-8")
                typer.echo(f"wrote {path_str}")
            return
        if check:
            drifted = doc_drift()
            for path_str in drifted:
                typer.echo(f"drifted: {path_str}")
            if drifted:
                fail("config docs drifted; run `just config-docs`.", ExitCode.ERROR)
            typer.echo("config docs in sync")
            return
        typer.echo(render_settings_table(), nl=False)
