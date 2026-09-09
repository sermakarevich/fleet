"""SSH tunnel keeping the GPU-box Ollama reachable at a local URL.

The ``opencode`` and ``pi`` coders talk to Ollama through a local port
(default ``127.0.0.1:11435``) that is an SSH forward to the GPU box.
``ensure_tunnel`` probes that URL and, if nothing answers, starts the
forward as a foreground ``ssh -N`` child owned by ``observability/daemon``
(a pidfile under ``$FLEET_HOME``), so ``fleet ollama tunnel stop/status``
see it. It is safe to call repeatedly: an already-up tunnel is a no-op,
and failures are reported, never raised.

Called by ``cli/daemons.py`` (supervisor startup, ``fleet ollama tunnel``
commands). Tunnel identity (host, ports) comes from ``TunnelSettings``,
built from ``RuntimeConfig`` — never from module constants or env vars.
"""

from __future__ import annotations

import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from http import HTTPStatus
from pathlib import Path
from urllib.parse import urlparse

from fleet.core.config import RuntimeConfig
from fleet.observability.daemon import DaemonSpec, start, tunnel_spec

DEFAULT_OLLAMA_URL = "http://127.0.0.1:11435/v1"
DEFAULT_SSH_HOST = "rtx"
DEFAULT_REMOTE_PORT = 11434
_LOOPBACK = {"127.0.0.1", "localhost", "::1"}


@dataclass(frozen=True)
class TunnelTimeouts:
    """Named seconds for every tunnel wait (no unnamed timeouts)."""

    probe_s: float = 2.0
    verify_s: float = 5.0
    connect_s: float = 10.0


@dataclass(frozen=True)
class TunnelSettings:
    """Everything the tunnel needs: where Ollama should answer, where it runs."""

    local_url: str = DEFAULT_OLLAMA_URL
    ssh_host: str = DEFAULT_SSH_HOST
    remote_port: int = DEFAULT_REMOTE_PORT
    timeouts: TunnelTimeouts = field(default_factory=TunnelTimeouts)

    @classmethod
    def from_config(cls, config: RuntimeConfig) -> TunnelSettings:
        """Build settings from runtime.toml fields (defaults keep today's values)."""
        return cls(
            local_url=config.opencode_ollama_url,
            ssh_host=config.ollama_ssh_host,
            remote_port=config.ollama_remote_port,
        )


@dataclass(frozen=True)
class TunnelResult:
    status: str  # "up" | "started" | "failed" | "skipped"
    local_port: int
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.status in ("up", "started", "skipped")


def tunnel_endpoint(url: str) -> tuple[str, int] | None:
    """(host, port) serving ``url``, or None when no tunnel can serve it.

    Only loopback URLs are tunnel candidates; anything else (a remote
    Ollama, a Unix socket) is used as-is and needs no tunnel.
    """
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if host not in _LOOPBACK:
        return None
    return (host, parsed.port or (443 if parsed.scheme == "https" else 80))


def tunnel_is_up(url: str, timeout: float = 2.0) -> bool:
    """True if an Ollama server answers at the URL's own host/port."""
    endpoint = tunnel_endpoint(url)
    if endpoint is None:
        return False
    _, port = endpoint
    scheme = urlparse(url).scheme or "http"
    try:
        with urllib.request.urlopen(
            f"{scheme}://127.0.0.1:{port}/api/tags", timeout=timeout
        ) as resp:
            return HTTPStatus.OK <= resp.status < HTTPStatus.MULTIPLE_CHOICES
    except (urllib.error.URLError, OSError, ValueError):
        return False


def ssh_argv(
    port: int,
    host: str,
    remote_port: int = DEFAULT_REMOTE_PORT,
    *,
    connect_s: float = 10.0,
) -> list[str]:
    """ssh holding one local forward in the foreground (owned by daemon.start)."""
    return [
        "ssh",
        "-N",  # no remote command: just hold the forward
        "-o",
        "BatchMode=yes",
        "-o",
        "ExitOnForwardFailure=yes",
        "-o",
        f"ConnectTimeout={int(connect_s)}",
        "-o",
        "ServerAliveInterval=15",
        "-o",
        "ServerAliveCountMax=3",
        "-L",
        f"127.0.0.1:{port}:127.0.0.1:{remote_port}",
        host,
    ]


def tunnel_daemon_spec(fleet_home: Path, settings: TunnelSettings) -> DaemonSpec:
    """Daemon spec for the tunnel ssh child; raises ValueError when unneeded."""
    endpoint = tunnel_endpoint(settings.local_url)
    if endpoint is None:
        raise ValueError(f"{settings.local_url} is not a loopback address; no tunnel needed")
    _, port = endpoint
    return tunnel_spec(
        fleet_home,
        ssh_argv(
            port,
            settings.ssh_host,
            settings.remote_port,
            connect_s=settings.timeouts.connect_s,
        ),
        local_port=port,
        ssh_host=settings.ssh_host,
        remote_port=settings.remote_port,
    )


def _verify_up(settings: TunnelSettings) -> bool:
    """Poll until Ollama answers or the verify window runs out."""
    deadline = time.monotonic() + settings.timeouts.verify_s
    while time.monotonic() < deadline:
        if tunnel_is_up(settings.local_url, timeout=settings.timeouts.probe_s):
            return True
        time.sleep(0.2)
    return False


def ensure_tunnel(settings: TunnelSettings, fleet_home: Path) -> TunnelResult:
    """Make sure Ollama is reachable at ``settings.local_url``.

    Starts the SSH forward through ``observability/daemon.start`` when it
    is down, so the child is tracked in a pidfile. Never raises — callers
    decide how loud to be about a ``failed`` result.
    """
    endpoint = tunnel_endpoint(settings.local_url)
    if endpoint is None:
        return TunnelResult(
            "skipped", 0, f"{settings.local_url} is not a loopback address; no tunnel needed"
        )
    _, port = endpoint
    if tunnel_is_up(settings.local_url, timeout=settings.timeouts.probe_s):
        return TunnelResult("up", port, f"ollama already reachable on 127.0.0.1:{port}")
    return _start_forward(settings, fleet_home, port)


def _start_forward(settings: TunnelSettings, fleet_home: Path, port: int) -> TunnelResult:
    """Start the ssh daemon for a down tunnel and verify Ollama answers."""
    try:
        started = start(tunnel_daemon_spec(fleet_home, settings))
    except FileNotFoundError:
        return TunnelResult("failed", port, "ssh binary not found on PATH")
    except OSError as exc:
        return TunnelResult("failed", port, f"could not start ssh tunnel: {exc}")
    if not started.alive and not started.already_running:
        return TunnelResult(
            "failed",
            port,
            "ssh tunnel process died immediately; see ollama_tunnel.daemon.log",
        )
    if not _verify_up(settings):
        return TunnelResult(
            "failed",
            port,
            f"ssh forward to {settings.ssh_host} started but ollama did not answer on {port}",
        )
    if started.already_running:
        return TunnelResult("up", port, f"ollama tunnel already running for 127.0.0.1:{port}")
    return TunnelResult(
        "started",
        port,
        f"tunnel established 127.0.0.1:{port} -> {settings.ssh_host}:{settings.remote_port}",
    )
