"""`fleet run` / `fleet serve` — background daemon management, and `fleet tunnel`.

`fleet run` and `fleet serve` are managed as detached background daemons via
`start | stop | restart | status | foreground` sub-commands. `foreground`
runs the service in the current terminal (and is what the daemon execs);
`start` spawns that entrypoint detached and tracks it through a PID file under
$FLEET_HOME. Daemons are CLI-managed only — they do NOT survive a reboot and
are NOT auto-restarted on crash; use `restart` to pick up code changes.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import typer
import uvicorn
from rich.console import Console

import fleet
from fleet.cli import bootstrap, render, subproc
from fleet.coders import get_coder
from fleet.core.config import RuntimeConfig
from fleet.core.errors import SubprocessTimeout
from fleet.integrations.ask_human.store import QuestionStore
from fleet.integrations.mcp_servers import ask_human_db_path
from fleet.integrations.ollama_tunnel import (
    TunnelResult,
    TunnelSettings,
    ensure_tunnel,
    tunnel_daemon_spec,
)
from fleet.observability.daemon import (
    DaemonSpec,
    StartResult,
    restart,
    serve_spec,
    start,
    stop,
    supervisor_spec,
    tunnel_spec,
)
from fleet.observability.pidfile import read as read_pid_record
from fleet.observability.process import service_status
from fleet.orchestrator import Supervisor, SupervisorState, default_services
from fleet.orchestrator.checks import DEFAULT_CHECKS
from fleet.orchestrator.rate_gauge import RateGauge
from fleet.serve.auth import warn_if_exposed
from fleet.state.journal import setup_supervisor_logger
from fleet.state.paths import log_dir as resolve_log_dir

if TYPE_CHECKING:
    import structlog

DEFAULT_SERVE_PORT = 7890
DEFAULT_SERVE_HOST = "0.0.0.0"  # all interfaces (LAN, Tailscale); use 127.0.0.1 for local only
_HOST_HELP = (
    "Interface to bind (0.0.0.0 = all interfaces incl. LAN/Tailscale; 127.0.0.1 = local only)."
)

_console = Console()


def _repo_root() -> Path:
    """Repo root containing the justfile (editable install: <repo>/src/fleet → <repo>)."""
    return Path(fleet.__file__).resolve().parents[2]


def _serve_stored_port() -> int | None:
    """Port recorded in the serve PID file, if any (used to preserve it on restart)."""
    spec = serve_spec(bootstrap.fleet_home(), DEFAULT_SERVE_HOST, DEFAULT_SERVE_PORT)
    record = read_pid_record(spec.pidfile)
    if record is None or record.extra.get("port") is None:
        return None
    try:
        return int(record.extra["port"])
    except (TypeError, ValueError):
        return None


def _serve_stored_host() -> str | None:
    """Host recorded in the serve PID file, if any (used to preserve it on restart)."""
    spec = serve_spec(bootstrap.fleet_home(), DEFAULT_SERVE_HOST, DEFAULT_SERVE_PORT)
    record = read_pid_record(spec.pidfile)
    host = record.extra.get("host") if record is not None else None
    return str(host) if host else None


def _resolve_serve_endpoint(port: int | None, host: str | None) -> tuple[str, int]:
    """Serve host/port: explicit flags win, else the running PID file, else defaults."""
    if port is None:
        port = _serve_stored_port()
    if host is None:
        host = _serve_stored_host()
    return (host or DEFAULT_SERVE_HOST, port if port is not None else DEFAULT_SERVE_PORT)


def _report_start(spec: DaemonSpec, result: StartResult, label: str) -> None:
    """Echo a start/restart outcome; exits nonzero when the daemon died immediately."""
    render.print_start_report(result, label, spec.logfile)


def _report_status(fleet_home: Path, name: str, label: str, restart_hint: str) -> None:
    """Echo daemon liveness from the process registry; exit nonzero when stopped."""
    status = service_status(name, fleet_home)
    render.print_service_status(label, status, restart_hint)
    if not status.alive:
        raise typer.Exit(1)


def _ensure_tunnel(fleet_home: Path, config: RuntimeConfig, log: structlog.BoundLogger) -> None:
    """Bring up the SSH tunnel to the GPU-box Ollama (non-fatal when it fails)."""
    settings = TunnelSettings.from_config(config)
    tunnel = ensure_tunnel(settings, fleet_home)
    if tunnel.status == "failed":
        log.warning("ollama_tunnel_failed", detail=tunnel.detail, url=settings.local_url)
        typer.echo(f"warning: ollama tunnel not available ({tunnel.detail})", err=True)
    else:
        log.info("ollama_tunnel", status=tunnel.status, detail=tunnel.detail)


def _build_supervisor(fleet_home: Path, config: RuntimeConfig) -> Supervisor:
    """Assemble the foreground supervisor with logging, tunnel, and services."""
    runtime_toml = fleet_home / "runtime.toml"
    log = setup_supervisor_logger(resolve_log_dir(fleet_home))
    _ensure_tunnel(fleet_home, config, log)
    question_store = QuestionStore(ask_human_db_path(fleet_home))
    return Supervisor(
        state=SupervisorState(
            config=config,
            fleet_home=fleet_home,
            runtime_toml_path=runtime_toml,
            queue=bootstrap.queue(fleet_home),
            log=log,
            rate_gauge=RateGauge(log=log),
            question_store=question_store,
        ),
        services=default_services(question_store=question_store),
        checks=DEFAULT_CHECKS,
    )


def _build_ui() -> None:
    """Run `just ui-build` from the repo root. Raises typer.Exit on failure.

    Called as the restart pre-step for `serve`, BEFORE the running server is
    stopped — so a failed/flaky build leaves the current server untouched.
    Skipped with a warning when there is no justfile (non-source install).
    """
    repo_root = _repo_root()
    if not (repo_root / "justfile").exists():
        _console.print(
            f"[yellow]Skipping UI build:[/] no justfile at {repo_root} (not a source checkout)."
        )
        return
    _console.print("Building UI ([bold]just ui-build[/])…")
    try:
        result = subproc.run(["just", "ui-build"], cwd=str(repo_root))
    except FileNotFoundError:
        _console.print("[yellow]Skipping UI build:[/] `just` is not installed.")
        return
    except SubprocessTimeout:
        _console.print("[red]UI build timed out[/] — leaving the running server untouched.")
        raise typer.Exit(1) from None
    if result.returncode != 0:
        _console.print("[red]UI build failed[/] — leaving the running server untouched.")
        raise typer.Exit(result.returncode)
    _console.print("[green]UI build complete.[/]")


def _register_run_commands(app: typer.Typer) -> None:
    """Wire `fleet run ...` (supervisor daemon commands)."""
    run_app = typer.Typer(
        no_args_is_help=True,
        help="Run the fleet supervisor (background daemon: start/stop/restart/status).",
    )
    app.add_typer(run_app, name="run")

    @run_app.command("foreground")
    def run_foreground() -> None:
        """Run the supervisor in the foreground (blocks). This is what `start` execs."""
        fleet_home = bootstrap.fleet_home()
        config = bootstrap.config(fleet_home)

        # Validate the configured default coder up-front so a typo fails fast.
        try:
            get_coder(config.coder)
        except ValueError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc
        supervisor = _build_supervisor(fleet_home, config)
        try:
            rc = asyncio.run(supervisor.run())
        except NotImplementedError as exc:
            typer.echo(f"Error: {exc}", err=True)
            raise typer.Exit(1) from exc
        raise typer.Exit(rc)

    @run_app.command("start")
    def run_start() -> None:
        """Start the supervisor as a background daemon."""
        spec = supervisor_spec(bootstrap.fleet_home())
        _report_start(spec, start(spec), "supervisor")

    @run_app.command("stop")
    def run_stop() -> None:
        """Stop the supervisor daemon (graceful SIGTERM, then SIGKILL)."""
        stopped = stop(supervisor_spec(bootstrap.fleet_home()))
        _console.print("supervisor stopped." if stopped else "supervisor not running.")

    @run_app.command("restart")
    def run_restart() -> None:
        """Restart the supervisor daemon to pick up code changes."""
        spec = supervisor_spec(bootstrap.fleet_home())
        _report_start(spec, restart(spec), "supervisor")

    @run_app.command("status")
    def run_status() -> None:
        """Show whether the supervisor daemon is running."""
        _report_status(bootstrap.fleet_home(), "supervisor", "supervisor", "fleet run restart")


def _register_serve_commands(app: typer.Typer) -> None:
    """Wire `fleet serve ...` (UI server daemon commands)."""
    serve_app = typer.Typer(
        no_args_is_help=True,
        help="Run the fleet UI server (background daemon: start/stop/restart/status).",
    )
    app.add_typer(serve_app, name="serve")

    @serve_app.command("foreground")
    def serve_foreground(
        port: Annotated[
            int, typer.Option("--port", help="Port to listen on.")
        ] = DEFAULT_SERVE_PORT,
        host: Annotated[str, typer.Option("--host", help=_HOST_HELP)] = DEFAULT_SERVE_HOST,
    ) -> None:
        """Run the UI server in the foreground (blocks). This is what `start` execs."""

        warn_if_exposed(host)
        uvicorn.run("fleet.serve.app:create_app", host=host, port=port, factory=True)

    @serve_app.command("start")
    def serve_start(
        port: Annotated[
            int, typer.Option("--port", help="Port to listen on.")
        ] = DEFAULT_SERVE_PORT,
        host: Annotated[str, typer.Option("--host", help=_HOST_HELP)] = DEFAULT_SERVE_HOST,
    ) -> None:
        """Start the UI server as a background daemon (FR-48, FR-49)."""
        spec = serve_spec(bootstrap.fleet_home(), host, port)
        _report_start(spec, start(spec), "serve")

    @serve_app.command("stop")
    def serve_stop() -> None:
        """Stop the UI server daemon."""
        stopped = stop(serve_spec(bootstrap.fleet_home(), DEFAULT_SERVE_HOST, DEFAULT_SERVE_PORT))
        _console.print("serve stopped." if stopped else "serve not running.")

    @serve_app.command("restart")
    def serve_restart(
        port: Annotated[
            int | None,
            typer.Option("--port", help="Port to listen on (default: reuse the running port)."),
        ] = None,
        host: Annotated[
            str | None,
            typer.Option("--host", help=_HOST_HELP + " Default: reuse the running host."),
        ] = None,
        no_build: Annotated[
            bool, typer.Option("--no-build", help="Skip `just ui-build` before restarting.")
        ] = False,
    ) -> None:
        """Rebuild the UI (`just ui-build`) and restart the server daemon.

        The build runs BEFORE the old server is stopped, so a failed build leaves
        the current server running. Pass --no-build to restart without rebuilding.
        """
        resolved_host, resolved_port = _resolve_serve_endpoint(port, host)
        spec = serve_spec(bootstrap.fleet_home(), resolved_host, resolved_port)
        before = None if no_build else _build_ui
        _report_start(spec, restart(spec, before_start=before), "serve")

    @serve_app.command("status")
    def serve_status() -> None:
        """Show whether the UI server daemon is running."""
        _report_status(bootstrap.fleet_home(), "serve", "serve", "fleet serve restart")


def register(app: typer.Typer) -> None:
    """Wire `fleet run`, `fleet serve`, `fleet tunnel`, and `fleet ollama tunnel`."""
    _register_run_commands(app)

    @app.command("tunnel")
    def tunnel_cmd() -> None:
        """Ensure the SSH tunnel to the GPU-box Ollama is up (starts it if needed)."""
        fleet_home = bootstrap.fleet_home()
        settings = TunnelSettings.from_config(bootstrap.config(fleet_home))
        _report_tunnel(ensure_tunnel(settings, fleet_home))

    _register_ollama_commands(app)
    _register_serve_commands(app)


def _report_tunnel(result: TunnelResult) -> None:
    """Echo an ensure/start outcome; exit nonzero when the tunnel failed."""
    if result.status == "failed":
        _console.print(f"[red]tunnel failed:[/red] {result.detail}")
        raise typer.Exit(1)
    _console.print(f"tunnel {result.status}: {result.detail}")


def _tunnel_stop_spec(fleet_home: Path, config: RuntimeConfig) -> DaemonSpec:
    """Spec for stopping: full forward facts when configured, pidfile-only otherwise."""
    try:
        return tunnel_daemon_spec(fleet_home, TunnelSettings.from_config(config))
    except ValueError:
        return tunnel_spec(fleet_home, [])


def _register_ollama_commands(app: typer.Typer) -> None:
    """Wire `fleet ollama tunnel start|stop|status` (tunnel daemon commands)."""
    ollama_app = typer.Typer(no_args_is_help=True, help="Ollama SSH tunnel to the GPU box.")
    app.add_typer(ollama_app, name="ollama")
    tunnel_app = typer.Typer(no_args_is_help=True, help="Manage the ollama SSH tunnel daemon.")
    ollama_app.add_typer(tunnel_app, name="tunnel")

    @tunnel_app.command("start")
    def ollama_tunnel_start() -> None:
        """Ensure the tunnel is up, starting its ssh daemon when needed."""
        fleet_home = bootstrap.fleet_home()
        settings = TunnelSettings.from_config(bootstrap.config(fleet_home))
        _report_tunnel(ensure_tunnel(settings, fleet_home))

    @tunnel_app.command("stop")
    def ollama_tunnel_stop() -> None:
        """Stop the tunnel ssh daemon."""
        fleet_home = bootstrap.fleet_home()
        stopped = stop(_tunnel_stop_spec(fleet_home, bootstrap.config(fleet_home)))
        _console.print("ollama tunnel stopped." if stopped else "ollama tunnel not running.")

    @tunnel_app.command("status")
    def ollama_tunnel_status() -> None:
        """Show whether the tunnel ssh daemon is running."""
        _report_status(
            bootstrap.fleet_home(), "ollama-tunnel", "ollama tunnel", "fleet ollama tunnel start"
        )
