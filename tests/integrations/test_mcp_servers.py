"""Tests for integrations.mcp_servers (the shared worker MCP definitions)."""

from pathlib import Path

from fleet.integrations.mcp_servers import (
    ASK_HUMAN_SERVER_MODULE,
    WEB_FETCH_SERVER_MODULE,
    ask_human_db_path,
    fleet_mcp_servers,
)


def test_returns_both_servers(tmp_path: Path):
    assert set(fleet_mcp_servers(tmp_path)) == {"ask_human", "web_fetch"}


def test_entries_have_command_args_env(tmp_path: Path):
    for entry in fleet_mcp_servers(tmp_path).values():
        assert isinstance(entry["command"], str) and entry["command"]
        assert isinstance(entry["args"], list) and entry["args"]
        assert isinstance(entry["env"], dict)


def test_ask_human_runs_fleet_server_module(tmp_path: Path):
    entry = fleet_mcp_servers(tmp_path)["ask_human"]
    assert entry["args"][-1] == ASK_HUMAN_SERVER_MODULE == (
        "fleet.integrations.ask_human.server"
    )
    assert "python" in entry["args"] and "-m" in entry["args"]


def test_web_fetch_runs_fleet_server_module(tmp_path: Path):
    entry = fleet_mcp_servers(tmp_path)["web_fetch"]
    assert entry["args"][-1] == WEB_FETCH_SERVER_MODULE == (
        "fleet.integrations.web_fetch.server"
    )


def test_ask_human_db_lives_under_home(tmp_path: Path):
    entry = fleet_mcp_servers(tmp_path)["ask_human"]
    assert entry["env"]["ASK_HUMAN_DB"] == str(tmp_path / "ask_human" / "questions.db")
    assert ask_human_db_path(tmp_path) == tmp_path / "ask_human" / "questions.db"


def test_db_path_does_not_point_at_personal_claude_dir(tmp_path: Path):
    entry = fleet_mcp_servers(tmp_path)["ask_human"]
    assert ".claude" not in entry["env"]["ASK_HUMAN_DB"]


def test_no_secrets_in_definitions(tmp_path: Path):
    blob = repr(fleet_mcp_servers(tmp_path)).lower()
    # The tmp dir itself embeds this test's name ("..._no_secrets_..."), so
    # scrub the home path before scanning for secret-looking markers.
    blob = blob.replace(str(tmp_path).lower(), "")
    for marker in ("token", "secret", "api_key", "apikey", "password"):
        assert marker not in blob
