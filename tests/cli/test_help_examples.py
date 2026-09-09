"""Every typer group carries an epilog with real examples; bd help lists _FLAGS rows."""

from __future__ import annotations

import pytest
from typer.main import get_command
from typer.testing import CliRunner

from fleet.beads.create_args import flag_table
from fleet.cli import beads as beads_mod
from fleet.cli.main import app

runner = CliRunner(env={"COLUMNS": "200"})

GROUP_EXAMPLES: dict[tuple[str, ...], list[str]] = {
    (): ['fleet bd create "Fix login redirect" --coder opencode', "fleet run restart"],
    ("run",): ["fleet run start", "fleet run status", "fleet run restart"],
    ("serve",): ["fleet serve start", "fleet serve status", "fleet serve restart"],
    ("ollama",): ["fleet ollama tunnel start", "fleet ollama tunnel status"],
    ("ollama", "tunnel"): [
        "fleet ollama tunnel start",
        "fleet ollama tunnel stop",
        "fleet ollama tunnel status",
    ],
    ("job",): ["fleet job view"],
    ("config",): ["fleet config show", "fleet config set"],
    ("telegram",): ["fleet telegram status", "fleet telegram test"],
    ("ask-human",): ["fleet ask-human install", "fleet ask-human serve"],
}


@pytest.mark.parametrize("path", list(GROUP_EXAMPLES))
def test_group_help_has_examples(path: tuple[str, ...]) -> None:
    result = runner.invoke(app, [*path, "--help"])
    assert result.exit_code == 0, result.output
    for example in GROUP_EXAMPLES[path]:
        assert example in result.output, f"{example!r} missing from {' '.join(path) or 'main'} help"


def test_bd_help_lists_every_intercepted_flag_row() -> None:
    rows = [spec for spec in flag_table().values() if not spec.forward_to_bd]
    assert rows, "expected at least one intercepted _FLAGS row"
    for spec in rows:
        assert spec.flag in beads_mod.BD_HELP, f"{spec.flag} missing from fleet bd help"


def test_bd_help_wired_into_command() -> None:
    command = get_command(app).commands["bd"]
    assert command.help == beads_mod.BD_HELP
