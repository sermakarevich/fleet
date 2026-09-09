"""The one source of truth for fleet-provided MCP servers handed to workers.

Every fleet worker is told (via ``templates/INSTRUCTION_COMMON.md``) to call
the ``ask_human`` MCP tool, so every coder must be handed that server
explicitly instead of relying on the operator's personal CLI config.
``fleet_mcp_servers`` returns the shared definitions; each coder adapts them
to its own config format (opencode JSON, Claude ``--mcp-config`` JSON, codex
``-c`` TOML overrides).

The returned mapping is ``{name: {"command": str, "args": list[str],
"env": dict[str, str]}}``. Values are plain data (paths, module names) —
never secrets — so coders may bake them into written config files.
"""

from __future__ import annotations

from pathlib import Path

ASK_HUMAN_SERVER_MODULE = "fleet.integrations.ask_human.server"
WEB_FETCH_SERVER_MODULE = "fleet.integrations.web_fetch.server"

ASK_HUMAN_DB_ENV = "ASK_HUMAN_DB"


def _fleet_root() -> Path:
    """Repo root that anchors ``uv --directory`` so workers run fleet's code."""
    return Path(__file__).parent.parent.parent.parent


def ask_human_db_path(fleet_home: Path) -> Path:
    """SQLite file shared by the ask_human server and (via the same env var)
    the operator frontends. Lives under FLEET_HOME, never in ~/.claude."""
    return fleet_home / "ask_human" / "questions.db"


def fleet_mcp_servers(fleet_home: Path) -> dict[str, dict]:
    """Return the MCP servers every fleet worker must be handed.

    *fleet_home* is FLEET_HOME (``state.paths.fleet_home()`` in production).
    ``ask_human`` gets ``ASK_HUMAN_DB`` pointed under *fleet_home* so questions land
    where the operator frontends (same env var) read them. ``web_fetch``
    needs no env of its own; coders that select its model (opencode) layer
    their ``FLEET_WEBFETCH_*`` vars on top of the returned ``env``.
    """
    root = str(_fleet_root())
    base_args = ["--directory", root, "run", "python", "-m"]
    return {
        "ask_human": {
            "command": "uv",
            "args": [*base_args, ASK_HUMAN_SERVER_MODULE],
            "env": {ASK_HUMAN_DB_ENV: str(ask_human_db_path(fleet_home))},
        },
        "web_fetch": {
            "command": "uv",
            "args": [*base_args, WEB_FETCH_SERVER_MODULE],
            "env": {},
        },
    }
