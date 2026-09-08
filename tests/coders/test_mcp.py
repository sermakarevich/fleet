"""Tests for coders/mcp.py: Claude's --mcp-config writer."""

import json
from pathlib import Path

import pytest

from fleet.coders.mcp import MCP_CONFIG_FILENAME, write_mcp_config
from fleet.integrations.mcp_servers import fleet_mcp_servers


def _servers(home: Path) -> dict[str, dict]:
    return fleet_mcp_servers(home)


def test_write_mcp_config_matches_shared_definitions(tmp_path: Path):
    home = tmp_path / "home"
    cfg_path = write_mcp_config(tmp_path / "attempt", _servers(home))
    assert cfg_path == tmp_path / "attempt" / MCP_CONFIG_FILENAME
    payload = json.loads(cfg_path.read_text(encoding="utf-8"))
    shared = _servers(home)
    for name, entry in shared.items():
        assert payload["mcpServers"][name]["command"] == entry["command"]
        assert payload["mcpServers"][name]["args"] == entry["args"]
        assert payload["mcpServers"][name]["env"] == entry["env"]


def test_write_mcp_config_creates_attempt_dir(tmp_path: Path):
    home = tmp_path / "home"
    cfg_path = write_mcp_config(tmp_path / "new" / "attempt", _servers(home))
    assert cfg_path.exists()


def test_write_failure_raises(tmp_path: Path):
    """A failed write raises OSError so the worker fails instead of launching blind."""
    blocker = tmp_path / "file"
    blocker.write_text("not a dir")
    with pytest.raises(OSError):
        write_mcp_config(blocker / "attempt", _servers(tmp_path))
