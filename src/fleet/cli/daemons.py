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
from typing import Annotated

import typer
import uvicorn
from rich.console import Console

import fleet
from fleet.cli import bootstrap, options, render, subproc
from fleet.cli.errors import ExitCode, fail
from fleet.cli.options import HostOption, PortOption
from fleet.core.config import RuntimeConfig
from fleet.core.errors import SubprocessTimeout
from fleet.integrations.ollama_tunnel import (
    TunnelResult,
    TunnelSettings,
    ensure_tunnel,
    tunnel_daemon_spec,
)
from fleet.observability.daemon import (
    DaemonSpec,
    StartResult,
    acquire_supervisor_lock,
    find_supervisor_orphans,
    release_supervisor_lock,
    restart,
    serve_spec,
    start,
    stop,
    supervisor_spec,
    tunnel_spec,
)
from fleet.observability.process import service_status
from fleet.serve.auth import warn_if_exposed

_RUN_EPILOG = "Examples:\n\n  fleet run start\n  fleet run status\n  fleet run restart"

_SERVE_EPILOG = (
    "Examples:\n\n"
    "  fleet serve start --port 7890\n"
    "  fleet serve status\n"
    "  fleet serve restart --no-build"
)

_OLLAMA_EPILOG = "Examples:\n\n  fleet ollama tunnel start\n  fleet ollama tunnel status"

_TUNNEL_EPILOG = (
    "Examples:\n\n"
    "  fleet ollama tunnel start\n"
    "  fleet ollama tunnel stop\n"
    "  fleet ollama tunnel status"
)

_console = Console()


def _repo_root() -> Path:
    """Repo root containing the justfile (editable install: <repo>/src/fleet → <repo>)."""
    return Path(fleet.__file__).resolve().parents[2]


def _report_start(spec: DaemonSpec, result: StartResult, label: str) -> None:
    """Echo a start/restart outcome; exits BACKEND when the daemon died immediately."""
    render.print_start_report(result, label, spec.logfile, code=int(ExitCode.BACKEND))


def _report_status(fleet_home: Path, name: str, label: str, restart_hint: str) -> None:
    """Echo daemon liveness from the process registry; exit ERROR when stopped."""
    status = service_status(name, fleet_home)
    render.print_service_status(label, status, restart_hint)
    if not status.alive:
        fail(f"{label} is stopped; run `{restart_hint}` to start it.")


def _build_ui(repo_root: Path | None = None) -> None:
    """Run `just ui-build` from the repo root. Raises typer.Exit on failure.

    Called as the restart pre-step for `serve`, BEFORE the running server is
    stopped — so a failed/flaky build leaves the current server untouched.
    Skipped with a warning when there is no justfile (non-source install).
    ``repo_root`` is an injection seam so tests pass a tmp dir instead of
    patching the private ``_repo_root`` helper.
    """
    root = repo_root if repo_root is not None else _repo_root()
    if not (root / "justfile").exists():
        _console.print(
            f"[yellow]Skipping UI build:[/] no justfile at {root} (not a source checkout)."
        )
        return
    _console.print("Building UI ([bold]just ui-build[/])…")
    try:
        result = subproc.run(["just", "ui-build"], cwd=str(root))
    except FileNotFoundError:
        _console.print("[yellow]Skipping UI build:[/] `just` is not installed.")
        return
    except SubprocessTimeout as exc:
        _console.print("[red]UI build timed out[/] — leaving the running server untouched.")
        fail(f"{' '.join(exc.argv)} timed out.", ExitCode.BACKEND)
    if result.returncode != 0:
        _console.print("[red]UI build failed[/] — leaving the running server untouched.")
        raise typer.Exit(result.returncode)
    _console.print("[green]UI build complete.[/]")


def _duplicate_message(fleet_home: Path) -> str:
    """Human detail for a refused second supervisor (names the holder)."""
    try:
        orphans = find_supervisor_orphans(fleet_home, None)
    except OSError:
        orphans = []
    holder = f" (pid {orphans[0]})" if orphans else ""
    return (
        f"another supervisor is already running for {fleet_home}{holder}; "
        "run `fleet run stop` to stop it before starting a new one."
    )


def _register_run_commands(app: typer.Typer) -> None:
    """Wire `fleet run ...` (supervisor daemon commands)."""
    run_app = typer.Typer(
        no_args_is_help=True,
        help="Run the fleet supervisor (background daemon: start/stop/restart/status).",
        epilog=_RUN_EPILOG,
    )
    app.add_typer(run_app, name="run")

    @run_app.command("foreground")
    def run_foreground() -> None:
        """Run the supervisor in the foreground (blocks). This is what `start` execs."""
        fleet_home = bootstrap.fleet_home()
        lock_fh = acquire_supervisor_lock(fleet_home)
        if lock_fh is None:
            fail(_duplicate_message(fleet_home), ExitCode.ERROR)
        try:
            supervisor = bootstrap.bootstrap_supervisor(fleet_home, bootstrap.config(fleet_home))
            try:
                rc = asyncio.run(supervisor.run())
            except NotImplementedError as exc:
                fail(str(exc))
            raise typer.Exit(rc)
        finally:
            release_supervisor_lock(lock_fh)

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
        epilog=_SERVE_EPILOG,
    )
    app.add_typer(serve_app, name="serve")

    @serve_app.command("foreground")
    def serve_foreground(
        port: PortOption = options.DEFAULT_SERVE_PORT,
        host: HostOption = options.DEFAULT_SERVE_HOST,
    ) -> None:
        """Run the UI server in the foreground (blocks). This is what `start` execs."""

        warn_if_exposed(host)
        uvicorn.run("fleet.serve.app:create_app", host=host, port=port, factory=True)

    @serve_app.command("start")
    def serve_start(
        port: PortOption = options.DEFAULT_SERVE_PORT,
        host: HostOption = options.DEFAULT_SERVE_HOST,
    ) -> None:
        """Start the UI server as a background daemon (FR-48, FR-49)."""
        spec = serve_spec(bootstrap.fleet_home(), host, port)
        _report_start(spec, start(spec), "serve")

    @serve_app.command("stop")
    def serve_stop() -> None:
        """Stop the UI server daemon."""
        stopped = stop(
            serve_spec(
                bootstrap.fleet_home(), options.DEFAULT_SERVE_HOST, options.DEFAULT_SERVE_PORT
            )
        )
        _console.print("serve stopped." if stopped else "serve not running.")

    @serve_app.command("restart")
    def serve_restart(
        port: Annotated[
            int | None,
            typer.Option("--port", help="Port to listen on (default: reuse the running port)."),
        ] = None,
        host: Annotated[
            str | None,
            typer.Option("--host", help="Interface to bind (default: reuse the running host)."),
        ] = None,
        no_build: Annotated[
            bool, typer.Option("--no-build", help="Skip `just ui-build` before restarting.")
        ] = False,
    ) -> None:
        """Rebuild the UI (`just ui-build`) and restart the server daemon.

        The build runs BEFORE the old server is stopped, so a failed build leaves
        the current server running. Pass --no-build to restart without rebuilding.
        """
        resolved_host, resolved_port = options.resolve_serve_endpoint(
            bootstrap.fleet_home(), port, host
        )
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

    @app.command(
        "tunnel",
        hidden=True,
        deprecated=True,
    )
    def tunnel_cmd() -> None:
        """Ensure the SSH tunnel to the GPU-box Ollama is up (starts it if needed)."""
        typer.echo(
            "warning: `fleet tunnel` is deprecated; use `fleet ollama tunnel start`.",
            err=True,
        )
        _ensure_ollama_tunnel()

    _register_ollama_commands(app)
    _register_serve_commands(app)


def _ensure_ollama_tunnel() -> None:
    """Ensure the ollama SSH tunnel is up, starting its ssh daemon when needed."""
    fleet_home = bootstrap.fleet_home()
    settings = TunnelSettings.from_config(bootstrap.config(fleet_home))
    _report_tunnel(ensure_tunnel(settings, fleet_home))


def _report_tunnel(result: TunnelResult) -> None:
    """Echo an ensure/start outcome; exit BACKEND when the tunnel failed."""
    if result.status == "failed":
        fail(f"tunnel failed: {result.detail}", ExitCode.BACKEND)
    _console.print(f"tunnel {result.status}: {result.detail}")


def _tunnel_stop_spec(fleet_home: Path, config: RuntimeConfig) -> DaemonSpec:
    """Spec for stopping: full forward facts when configured, pidfile-only otherwise."""
    try:
        return tunnel_daemon_spec(fleet_home, TunnelSettings.from_config(config))
    except ValueError:
        return tunnel_spec(fleet_home, [])


def _register_ollama_commands(app: typer.Typer) -> None:
    """Wire `fleet ollama tunnel start|stop|status` (tunnel daemon commands)."""
    ollama_app = typer.Typer(
        no_args_is_help=True,
        help="Ollama SSH tunnel to the GPU box.",
        epilog=_OLLAMA_EPILOG,
    )
    app.add_typer(ollama_app, name="ollama")
    tunnel_app = typer.Typer(
        no_args_is_help=True, help="Manage the ollama SSH tunnel daemon.", epilog=_TUNNEL_EPILOG
    )
    ollama_app.add_typer(tunnel_app, name="tunnel")

    @tunnel_app.command("start")
    def ollama_tunnel_start() -> None:
        """Ensure the tunnel is up, starting its ssh daemon when needed."""
        _ensure_ollama_tunnel()

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
