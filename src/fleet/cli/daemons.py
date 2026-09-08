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
import subprocess
from pathlib import Path
from typing import Annotated

import typer
import uvicorn
from rich.console import Console

import fleet
from fleet.beads.queue import BeadsQueue
from fleet.coders import get_coder
from fleet.core.limits import LOG_ROOT
from fleet.integrations.ask_human.store import QuestionStore
from fleet.integrations.ollama_tunnel import ensure_tunnel
from fleet.observability.daemon import Daemon, StartResult, serve_spec, supervisor_spec
from fleet.orchestrator import Supervisor, SupervisorState, default_services
from fleet.orchestrator.checks import DEFAULT_CHECKS
from fleet.orchestrator.rate_gauge import RateGauge
from fleet.state.config_file import load as load_config
from fleet.state.journal import setup_supervisor_logger
from fleet.state.paths import fleet_home

DEFAULT_SERVE_PORT = 7890
DEFAULT_SERVE_HOST = "0.0.0.0"  # all interfaces (LAN, Tailscale); use 127.0.0.1 for local only
_HOST_HELP = (
    "Interface to bind (0.0.0.0 = all interfaces incl. LAN/Tailscale; 127.0.0.1 = local only)."
)

_console = Console()


def _repo_root() -> Path:
    """Repo root containing the justfile (editable install: <repo>/src/fleet → <repo>)."""
    return Path(fleet.__file__).resolve().parents[2]


def _resolve_log_dir(home: Path) -> Path:
    log_root = Path(LOG_ROOT)
    return log_root if log_root.is_absolute() else home / log_root


def _serve_stored_port() -> int | None:
    """Port recorded in the serve PID file, if any (used to preserve it on restart)."""
    data = Daemon(serve_spec(fleet_home(), DEFAULT_SERVE_HOST, DEFAULT_SERVE_PORT)).read_pidfile()
    if not data or data.get("port") is None:
        return None
    try:
        return int(data["port"])
    except (TypeError, ValueError):
        return None


def _serve_stored_host() -> str | None:
    """Host recorded in the serve PID file, if any (used to preserve it on restart)."""
    data = Daemon(serve_spec(fleet_home(), DEFAULT_SERVE_HOST, DEFAULT_SERVE_PORT)).read_pidfile()
    host = data.get("host") if data else None
    return str(host) if host else None


def _tail_logfile(path: Path, n: int = 20) -> None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    if not lines:
        return
    _console.print(f"[dim]--- last {min(n, len(lines))} lines of {path} ---[/]")
    for line in lines[-n:]:
        _console.print(line)


def _report_start(daemon: Daemon, result: StartResult, label: str) -> None:
    """Echo the outcome of a start/restart; exit nonzero if it died immediately."""
    if result.already_running:
        _console.print(f"[yellow]{label} already running[/] (pid {result.pid}).")
        return
    if not result.alive:
        _console.print(f"[red]{label} failed to start[/] — process exited immediately.")
        _tail_logfile(daemon.spec.logfile)
        raise typer.Exit(1)
    _console.print(f"[green]{label} started[/] (pid {result.pid}). Logs: {daemon.spec.logfile}")


def _report_status(daemon: Daemon, label: str) -> None:
    """Echo daemon status. Exits nonzero when stopped (so scripts can branch)."""
    st = daemon.status()
    if not st.running:
        _console.print(f"{label}: [red]stopped[/]")
        raise typer.Exit(1)
    parts = [f"pid {st.pid}"]
    if st.started_at:
        parts.append(f"since {st.started_at}")
    if st.extra.get("host"):
        parts.append(f"host {st.extra['host']}")
    if st.extra.get("port") is not None:
        parts.append(f"port {st.extra['port']}")
    if st.version_fingerprint:
        parts.append(f"fingerprint {st.version_fingerprint}")
    _console.print(f"{label}: [green]running[/] ({', '.join(parts)})")
    if st.stale:
        _restart_cmd = (
            "fleet run restart" if daemon.spec.name == "supervisor" else "fleet serve restart"
        )
        _console.print(
            f"[bold yellow]⚠  {label} is running stale code[/] — "
            f"run [bold]{_restart_cmd}[/] to pick up changes."
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
        result = subprocess.run(["just", "ui-build"], cwd=str(repo_root), check=False)
    except FileNotFoundError:
        _console.print("[yellow]Skipping UI build:[/] `just` is not installed.")
        return
    if result.returncode != 0:
        _console.print("[red]UI build failed[/] — leaving the running server untouched.")
        raise typer.Exit(result.returncode)
    _console.print("[green]UI build complete.[/]")


def register(app: typer.Typer) -> None:  # noqa: PLR0915  # ADR 0006 bead 12
    run_app = typer.Typer(
        no_args_is_help=True,
        help="Run the fleet supervisor (background daemon: start/stop/restart/status).",
    )
    app.add_typer(run_app, name="run")

    @run_app.command("foreground")
    def run_foreground() -> None:
        """Run the supervisor in the foreground (blocks). This is what `start` execs."""
        home = fleet_home()
        runtime_toml = home / "runtime.toml"
        cfg = load_config(runtime_toml)

        # Validate the configured default coder up-front so a typo fails fast.
        try:
            get_coder(cfg.coder)
        except ValueError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc

        q = BeadsQueue(home)
        log_root = Path(LOG_ROOT)
        if not log_root.is_absolute():
            log_root = home / log_root
        log = setup_supervisor_logger(log_root)

        # Bring up the SSH tunnel to the rtx Ollama box so opencode/pi tasks can
        # run. Non-fatal: claude/agy/codex tasks do not need it.
        tunnel = ensure_tunnel(cfg.opencode_ollama_url)
        if tunnel.status == "failed":
            log.warning("ollama_tunnel_failed", detail=tunnel.detail, url=cfg.opencode_ollama_url)
            typer.echo(f"warning: ollama tunnel not available ({tunnel.detail})", err=True)
        else:
            log.info("ollama_tunnel", status=tunnel.status, detail=tunnel.detail)
        supervisor = Supervisor(
            state=SupervisorState(
                config=cfg,
                project_root=home,
                runtime_toml_path=runtime_toml,
                queue=q,
                log=log,
                rate_gauge=RateGauge(log=log),
            ),
            services=default_services(question_store=QuestionStore()),
            checks=DEFAULT_CHECKS,
        )
        try:
            rc = asyncio.run(supervisor.run())
        except NotImplementedError as exc:
            typer.echo(f"Error: {exc}", err=True)
            raise typer.Exit(1) from exc
        raise typer.Exit(rc)

    @run_app.command("start")
    def run_start() -> None:
        """Start the supervisor as a background daemon."""
        daemon = Daemon(supervisor_spec(fleet_home()))
        _report_start(daemon, daemon.start(), "supervisor")

    @run_app.command("stop")
    def run_stop() -> None:
        """Stop the supervisor daemon (graceful SIGTERM, then SIGKILL)."""
        daemon = Daemon(supervisor_spec(fleet_home()))
        stopped = daemon.stop()
        _console.print("supervisor stopped." if stopped else "supervisor not running.")

    @run_app.command("restart")
    def run_restart() -> None:
        """Restart the supervisor daemon to pick up code changes."""
        daemon = Daemon(supervisor_spec(fleet_home()))
        _report_start(daemon, daemon.restart(), "supervisor")

    @run_app.command("status")
    def run_status() -> None:
        """Show whether the supervisor daemon is running."""
        _report_status(Daemon(supervisor_spec(fleet_home())), "supervisor")

    @app.command("tunnel")
    def tunnel_cmd() -> None:
        """Ensure the SSH tunnel to the rtx Ollama box is up (starts it if needed)."""
        cfg = load_config(fleet_home() / "runtime.toml")
        result = ensure_tunnel(cfg.opencode_ollama_url)
        if result.status == "failed":
            _console.print(f"[red]tunnel failed:[/red] {result.detail}")
            raise typer.Exit(1)
        _console.print(f"tunnel {result.status}: {result.detail}")

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

        uvicorn.run("fleet.serve.app:create_app", host=host, port=port, factory=True)

    @serve_app.command("start")
    def serve_start(
        port: Annotated[
            int, typer.Option("--port", help="Port to listen on.")
        ] = DEFAULT_SERVE_PORT,
        host: Annotated[str, typer.Option("--host", help=_HOST_HELP)] = DEFAULT_SERVE_HOST,
    ) -> None:
        """Start the UI server as a background daemon (FR-48, FR-49)."""
        daemon = Daemon(serve_spec(fleet_home(), host, port))
        _report_start(daemon, daemon.start(), "serve")

    @serve_app.command("stop")
    def serve_stop() -> None:
        """Stop the UI server daemon."""
        daemon = Daemon(serve_spec(fleet_home(), DEFAULT_SERVE_HOST, DEFAULT_SERVE_PORT))
        stopped = daemon.stop()
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
        if port is None:
            port = _serve_stored_port()
        if host is None:
            host = _serve_stored_host()
        resolved_port = port if port is not None else DEFAULT_SERVE_PORT
        resolved_host = host or DEFAULT_SERVE_HOST
        daemon = Daemon(serve_spec(fleet_home(), resolved_host, resolved_port))
        before = None if no_build else _build_ui
        _report_start(daemon, daemon.restart(before_start=before), "serve")

    @serve_app.command("status")
    def serve_status() -> None:
        """Show whether the UI server daemon is running."""
        _report_status(
            Daemon(serve_spec(fleet_home(), DEFAULT_SERVE_HOST, DEFAULT_SERVE_PORT)), "serve"
        )
