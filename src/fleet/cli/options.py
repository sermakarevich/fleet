"""Shared typer option/argument aliases and serve endpoint resolution.

Called by every ``cli/*`` command module so ``--host``/``--port``/task-id
are declared once. Serve defaults come from ``core/config.py`` (single
source); the stored host/port come from the serve PID file, read once by
``serve_stored``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from fleet.core.config import RuntimeConfig
from fleet.observability.daemon import serve_spec
from fleet.observability.pidfile import read as read_pid_record

_DEFAULTS = RuntimeConfig()

#: Default bind address (all interfaces; see RuntimeConfig.serve_host).
DEFAULT_SERVE_HOST: str = _DEFAULTS.serve_host
#: Default UI port (see RuntimeConfig.serve_port).
DEFAULT_SERVE_PORT: int = _DEFAULTS.serve_port

_HOST_HELP = (
    "Interface to bind (0.0.0.0 = all interfaces incl. LAN/Tailscale; 127.0.0.1 = local only)."
)

HostOption = Annotated[str, typer.Option("--host", help=_HOST_HELP)]
"""`--host` flag for serve commands; the default is given at each use site."""

PortOption = Annotated[int, typer.Option("--port", help="Port to listen on.")]
"""`--port` flag for serve commands; the default is given at each use site."""

TaskIdArgument = Annotated[str, typer.Argument(help="Task ID.")]
"""Positional task id shared by every task command."""


def serve_stored(fleet_home: Path) -> tuple[str, int] | None:
    """(host, port) recorded in the serve PID file, or None when absent/incomplete."""
    record = read_pid_record(serve_spec(fleet_home, DEFAULT_SERVE_HOST, DEFAULT_SERVE_PORT).pidfile)
    if record is None:
        return None
    try:
        return (str(record.extra["host"]), int(record.extra["port"]))
    except (KeyError, TypeError, ValueError):
        return None


def resolve_serve_endpoint(fleet_home: Path, port: int | None, host: str | None) -> tuple[str, int]:
    """Serve host/port: explicit flags win, else the running PID file, else defaults."""
    stored_host, stored_port = serve_stored(fleet_home) or (None, None)
    return (host or stored_host or DEFAULT_SERVE_HOST, port or stored_port or DEFAULT_SERVE_PORT)
