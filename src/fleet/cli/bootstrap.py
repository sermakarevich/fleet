"""The one place CLI commands get their dependencies.

Called by every ``cli/*`` command module. Path resolution lives in
``state/paths`` (not here): commands call those helpers instead of
resolving paths, queues, or config themselves. Foreground supervisor
assembly also lives here so `fleet run foreground` stays a thin command.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import typer

from fleet.beads.queue import BeadsQueue
from fleet.cli.errors import ExitCode, fail
from fleet.coders import get_coder
from fleet.core.config import RuntimeConfig
from fleet.integrations.ask_human.store import QuestionStore
from fleet.integrations.mcp_servers import ask_human_db_path
from fleet.integrations.ollama_tunnel import TunnelSettings, ensure_tunnel
from fleet.orchestrator import Supervisor, SupervisorState, default_services
from fleet.orchestrator.checks import DEFAULT_CHECKS
from fleet.orchestrator.rate_gauge import RateGauge
from fleet.state import paths
from fleet.state.config_file import load as load_config
from fleet.state.journal import setup_supervisor_logger
from fleet.state.paths import log_dir as resolve_log_dir

if TYPE_CHECKING:
    import structlog


def fleet_home() -> Path:
    """Fleet home directory (``$FLEET_HOME`` or ``~/.fleet``)."""
    return paths.fleet_home()


def queue(fleet_home: Path) -> BeadsQueue:
    """Beads queue bound to the fleet home."""
    return BeadsQueue(fleet_home)


def config(fleet_home: Path) -> RuntimeConfig:
    """Runtime config, creating ``runtime.toml`` with defaults when missing."""
    return load_config(fleet_home / "runtime.toml")


def ensure_ollama_tunnel(
    fleet_home: Path, config: RuntimeConfig, log: structlog.BoundLogger
) -> None:
    """Bring up the SSH tunnel to the GPU-box Ollama (non-fatal when it fails)."""
    settings = TunnelSettings.from_config(config)
    tunnel = ensure_tunnel(settings, fleet_home)
    if tunnel.status == "failed":
        log.warning("ollama_tunnel_failed", detail=tunnel.detail, url=settings.local_url)
        typer.echo(f"warning: ollama tunnel not available ({tunnel.detail})", err=True)
    else:
        log.info("ollama_tunnel", status=tunnel.status, detail=tunnel.detail)


def bootstrap_supervisor(fleet_home: Path, config: RuntimeConfig) -> Supervisor:
    """Assemble the foreground supervisor with logging, tunnel, and services."""
    try:
        get_coder(config.coder)
    except ValueError as exc:
        fail(str(exc), ExitCode.USAGE)
    log = setup_supervisor_logger(resolve_log_dir(fleet_home))
    ensure_ollama_tunnel(fleet_home, config, log)
    question_store = QuestionStore(ask_human_db_path(fleet_home))
    return Supervisor(
        state=SupervisorState(
            config=config,
            fleet_home=fleet_home,
            runtime_toml_path=fleet_home / "runtime.toml",
            queue=queue(fleet_home),
            log=log,
            rate_gauge=RateGauge(log=log),
            question_store=question_store,
        ),
        services=default_services(question_store=question_store),
        checks=DEFAULT_CHECKS,
    )
