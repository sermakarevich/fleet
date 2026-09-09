"""Process facts for fleet's managed services, one owner.

Called by serve/api/supervisor.py, serve/app.py (healthz) and
serve/api/tasks_actions.py (kill liveness check). Reads pid files through
observability/daemon.py — nobody else parses them.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

from fleet.core.process import pid_alive
from fleet.observability.daemon import (
    TUNNEL_PIDFILE_NAME,
    DaemonSpec,
    code_fingerprint,
    find_supervisor_orphans,
    supervisor_spec,
)
from fleet.state import paths as state_paths

from .pidfile import PidFile
from .pidfile import read as read_pid_file


@dataclass(frozen=True)
class ServiceStatus:
    """Liveness fact for one managed service."""

    pid: int | None
    alive: bool
    since: str | None
    fingerprint: str | None
    stale: bool = False
    # Supervisor pids alive for this fleet home that the pidfile misses.
    orphan_pids: tuple[int, ...] = ()


def _serve_spec(fleet_home: Path) -> DaemonSpec:
    """Reader spec for `fleet serve` (pidfile only; argv unused for status)."""
    return DaemonSpec(
        name="serve",
        pidfile=fleet_home / ".serve.pid",
        logfile=fleet_home / "logs" / "serve.daemon.log",
        argv=[],
        cwd=fleet_home,
        stop_timeout=10.0,
    )


def _tunnel_spec(fleet_home: Path) -> DaemonSpec:
    """Reader spec for the ollama tunnel (pidfile only; argv unused for status)."""
    return DaemonSpec(
        name="ollama-tunnel",
        pidfile=fleet_home / TUNNEL_PIDFILE_NAME,
        logfile=fleet_home / "logs" / "ollama_tunnel.daemon.log",
        argv=[],
        cwd=fleet_home,
        stop_timeout=10.0,
    )


_SPECS: dict[str, Callable[[Path], DaemonSpec]] = {
    "supervisor": supervisor_spec,
    "serve": _serve_spec,
    "ollama-tunnel": _tunnel_spec,
}


def registered_services() -> list[str]:
    """Names service_status() understands."""
    return sorted(_SPECS)


class ServiceRegistry:
    """Liveness of managed services for one fleet home."""

    def __init__(self, fleet_home: Path) -> None:
        self.fleet_home = fleet_home

    def status(self, name: str) -> ServiceStatus:
        """Read the pid file for *name*; unknown names report not alive."""
        build = _SPECS.get(name)
        if build is None:
            return ServiceStatus(pid=None, alive=False, since=None, fingerprint=None)
        record = read_pid_file(build(self.fleet_home).pidfile)
        status = _from_pid_record(record)
        if name != "supervisor":
            return status
        return replace(status, orphan_pids=tuple(self._orphans(record)))

    def _orphans(self, record: PidFile | None) -> list[int]:
        """Untracked supervisor pids for this fleet home (best effort)."""
        try:
            known = record.pid if record is not None else None
            return find_supervisor_orphans(self.fleet_home, known)
        except OSError:
            return []

    def supervisor_running(self) -> bool:
        """True when the supervisor pid file points at a live process."""
        return self.status("supervisor").alive


def _from_pid_record(record: PidFile | None) -> ServiceStatus:
    """Liveness fact from a pidfile record; a missing record means not alive."""
    if record is None:
        return ServiceStatus(pid=None, alive=False, since=None, fingerprint=None)
    alive = pid_alive(record.pid)
    stored = record.fingerprint
    return ServiceStatus(
        pid=record.pid,
        alive=alive,
        since=record.started_at,
        fingerprint=stored,
        stale=stored is not None and stored != code_fingerprint(),
    )


def service_status(name: str, fleet_home: Path | None = None) -> ServiceStatus:
    """Liveness fact for *name* (``supervisor``, ``serve``, or ``ollama-tunnel``)."""
    return ServiceRegistry(
        fleet_home if fleet_home is not None else state_paths.fleet_home()
    ).status(name)
