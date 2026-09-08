"""Claude's ``--mcp-config`` writer: which file, what goes in it.

Server definitions come from ``integrations.mcp_servers.fleet_mcp_servers``
(the same source opencode and codex use); only the file layout is Claude's.
Raises ``OSError`` when the write fails so the worker fails the step instead
of launching claude without ``ask_human``. Called by
``coders/claude.py`` (``build_argv`` and ``write_runtime_config``).
"""

from __future__ import annotations

import json
from pathlib import Path

MCP_CONFIG_FILENAME = "mcp.json"


def write_mcp_config(attempt_dir: Path, servers: dict[str, dict]) -> Path:
    """Write ``{"mcpServers": ...}`` into ``attempt_dir/mcp.json`` and return its path.

    *servers* is ``integrations.mcp_servers.fleet_mcp_servers`` output
    (``{name: {"command", "args", "env"}}``), adapted to Claude's config
    shape. Values are paths and module names, never secrets.
    """
    adapted = {
        name: {
            "command": entry["command"],
            "args": list(entry["args"]),
            "env": dict(entry["env"]),
        }
        for name, entry in servers.items()
    }
    attempt_dir.mkdir(parents=True, exist_ok=True)
    path = attempt_dir / MCP_CONFIG_FILENAME
    path.write_text(json.dumps({"mcpServers": adapted}, indent=2) + "\n", encoding="utf-8")
    return path
