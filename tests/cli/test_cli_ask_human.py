"""Tests for the `fleet ask-human` CLI commands (vendored question broker)."""

from __future__ import annotations

from unittest.mock import patch

from typer.testing import CliRunner

from fleet.cli import app

runner = CliRunner()


def test_ask_human_help_lists_commands() -> None:
    result = runner.invoke(app, ["ask-human", "--help"])
    assert result.exit_code == 0
    for cmd in ("serve", "install"):
        assert cmd in result.output


def test_install_requires_claude_cli(tmp_path) -> None:
    with patch("shutil.which", return_value=None):
        result = runner.invoke(app, ["ask-human", "install"])
    assert result.exit_code == 1
    assert "claude" in result.output


def test_install_registers_with_claude_mcp_add() -> None:
    calls: list[list[str]] = []

    class _Done:
        returncode = 0
        stderr = ""

    def fake_run(argv, **kwargs):
        calls.append(list(argv))
        return _Done()

    def fake_which(name):
        return {"claude": "/usr/local/bin/claude", "fleet": "/usr/local/bin/fleet"}.get(
            name
        )

    with (
        patch("shutil.which", side_effect=fake_which),
        patch("fleet.cli.subprocess.run", side_effect=fake_run),
    ):
        result = runner.invoke(app, ["ask-human", "install"])

    assert result.exit_code == 0
    assert "Registered MCP server 'ask_human'" in result.output
    add = [c for c in calls if c[1:3] == ["mcp", "add"]]
    assert len(add) == 1
    assert add[0] == [
        "/usr/local/bin/claude",
        "mcp",
        "add",
        "ask_human",
        "--scope",
        "user",
        "--",
        "/usr/local/bin/fleet",
        "ask-human",
        "serve",
    ]
