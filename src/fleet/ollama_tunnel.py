"""Ensure the SSH tunnel to the rtx Ollama box is up.

The ``opencode`` and ``pi`` coders talk to Ollama through a local port
(default ``127.0.0.1:11435``) that is an SSH forward to ``rtx:11434``.
This module probes that port and, if nothing answers, starts a background
``ssh -f -N -L`` forward. It is safe to call repeatedly: an already-up
tunnel is a no-op, and failures are reported, never raised.
"""

from __future__ import annotations

import os
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from urllib.parse import urlparse

DEFAULT_OLLAMA_URL = "http://127.0.0.1:11435/v1"
DEFAULT_SSH_HOST = "rtx"
DEFAULT_REMOTE_PORT = 11434
_LOOPBACK = {"127.0.0.1", "localhost", "::1"}


@dataclass(frozen=True)
class TunnelResult:
    status: str  # "up" | "started" | "failed" | "skipped"
    local_port: int
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.status in ("up", "started", "skipped")


def ssh_host() -> str:
    """SSH host alias for the GPU box (override with ``FLEET_OLLAMA_SSH_HOST``)."""
    return os.environ.get("FLEET_OLLAMA_SSH_HOST", DEFAULT_SSH_HOST)


def local_port(url: str) -> int | None:
    """Return the local port of ``url`` if it points at loopback, else None."""
    parsed = urlparse(url)
    if parsed.hostname not in _LOOPBACK:
        return None
    return parsed.port or (443 if parsed.scheme == "https" else 80)


def tunnel_is_up(port: int, timeout: float = 2.0) -> bool:
    """True if an Ollama server answers on ``127.0.0.1:<port>``."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/tags", timeout=timeout) as resp:
            return 200 <= resp.status < 300
    except (urllib.error.URLError, OSError, ValueError):
        return False


def ssh_argv(port: int, host: str, remote_port: int = DEFAULT_REMOTE_PORT) -> list[str]:
    return [
        "ssh",
        "-f",  # go to background once the forward is established
        "-N",  # no remote command
        "-o", "BatchMode=yes",
        "-o", "ExitOnForwardFailure=yes",
        "-o", "ConnectTimeout=10",
        "-o", "ServerAliveInterval=15",
        "-o", "ServerAliveCountMax=3",
        "-L", f"127.0.0.1:{port}:127.0.0.1:{remote_port}",
        host,
    ]


def ensure_tunnel(
    url: str = DEFAULT_OLLAMA_URL,
    *,
    host: str | None = None,
    remote_port: int = DEFAULT_REMOTE_PORT,
) -> TunnelResult:
    """Make sure Ollama is reachable at ``url``; start the SSH tunnel if not.

    Never raises — callers decide how loud to be about a ``failed`` result.
    """
    port = local_port(url)
    if port is None:
        return TunnelResult("skipped", 0, f"{url} is not a loopback address; no tunnel needed")
    if tunnel_is_up(port):
        return TunnelResult("up", port, f"ollama already reachable on 127.0.0.1:{port}")

    host = host or ssh_host()
    try:
        proc = subprocess.run(
            ssh_argv(port, host, remote_port),
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except FileNotFoundError:
        return TunnelResult("failed", port, "ssh binary not found on PATH")
    except subprocess.TimeoutExpired:
        return TunnelResult("failed", port, f"ssh to {host} timed out")
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout).strip() or f"ssh exited {proc.returncode}"
        return TunnelResult("failed", port, err)
    if not tunnel_is_up(port, timeout=5.0):
        return TunnelResult(
            "failed", port, f"ssh forward to {host} established but ollama did not answer on {port}"
        )
    return TunnelResult("started", port, f"tunnel established 127.0.0.1:{port} -> {host}:{remote_port}")
