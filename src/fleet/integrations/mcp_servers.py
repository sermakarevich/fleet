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

Two environment details live here: the fleet root (``FLEET_ROOT`` override,
else located from the installed ``fleet`` package) anchors ``uv
--directory`` so workers run this checkout's code; when ``uv`` is not on
PATH the servers run with the current interpreter instead
(``sys.executable -m``), which works in venvs without uv.
"""

from __future__ import annotations

import importlib.resources
import os
import shutil
import sys
from pathlib import Path

ASK_HUMAN_SERVER_MODULE = "fleet.integrations.ask_human.server"
WEB_FETCH_SERVER_MODULE = "fleet.integrations.web_fetch.server"

ASK_HUMAN_DB_ENV = "ASK_HUMAN_DB"

#: Override for the fleet root (containers, relocated checkouts).
FLEET_ROOT_ENV = "FLEET_ROOT"


def _fleet_root() -> Path:
    """Repo root that anchors ``uv --directory`` so workers run fleet's code.

    ``FLEET_ROOT`` wins when set. Otherwise the installed ``fleet``
    package locates itself: an editable src layout (``<root>/src/fleet``)
    resolves two parents up when that directory holds the justfile; a
    site-packages install (no justfile above it) falls back to the
    package's parent directory.
    """
    override = os.environ.get(FLEET_ROOT_ENV)
    if override:
        return Path(override)
    package_dir = Path(str(importlib.resources.files("fleet")))
    if (package_dir.parent.parent / "justfile").exists():
        return package_dir.parent.parent
    return package_dir.parent


def _server_launch(module: str, root: Path) -> tuple[str, list[str]]:
    """(command, args) running an MCP server module from *root*.

    Under ``uv`` (on PATH) the server runs pinned to *root* so workers
    always use this checkout's code; without ``uv`` it runs with the
    current interpreter, which works in plain venvs.
    """
    if shutil.which("uv") is not None:
        return "uv", ["--directory", str(root), "run", "python", "-m", module]
    return sys.executable, ["-m", module]


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
    root = _fleet_root()
    ask_command, ask_args = _server_launch(ASK_HUMAN_SERVER_MODULE, root)
    fetch_command, fetch_args = _server_launch(WEB_FETCH_SERVER_MODULE, root)
    return {
        "ask_human": {
            "command": ask_command,
            "args": ask_args,
            "env": {ASK_HUMAN_DB_ENV: str(ask_human_db_path(fleet_home))},
        },
        "web_fetch": {
            "command": fetch_command,
            "args": fetch_args,
            "env": {},
        },
    }
