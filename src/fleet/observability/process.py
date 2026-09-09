"""Process facts for fleet's managed services, one owner.

Called by serve/api/supervisor.py, serve/app.py (healthz) and
serve/api/tasks_actions.py (kill liveness check). Reads pid files through
observability/daemon.py — nobody else parses them.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from fleet.core.process import pid_alive
from fleet.observability.daemon import (
    DaemonSpec,
    code_fingerprint,
    read_pidfile,
    supervisor_spec,
)
from fleet.state import paths as state_paths


@dataclass(frozen=True)
class ServiceStatus:
    """Liveness fact for one managed service."""

    pid: int | None
    alive: bool
    since: str | None
    fingerprint: str | None
    stale: bool = False


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


_SPECS: dict[str, Callable[[Path], DaemonSpec]] = {
    "supervisor": supervisor_spec,
    "serve": _serve_spec,
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
        data = read_pidfile(build(self.fleet_home)) or {}
        return _from_pid_data(data)

    def supervisor_running(self) -> bool:
        """True when the supervisor pid file points at a live process."""
        return self.status("supervisor").alive


def _from_pid_data(data: dict) -> ServiceStatus:
    raw_pid = data.get("pid", 0)
    try:
        pid = int(raw_pid) or None
    except (TypeError, ValueError):
        pid = None
    alive = pid is not None and pid_alive(pid)
    stored = data.get("version_fingerprint")
    return ServiceStatus(
        pid=pid,
        alive=alive,
        since=data.get("started_at"),
        fingerprint=stored,
        stale=stored is not None and stored != code_fingerprint(),
    )


def service_status(name: str, fleet_home: Path | None = None) -> ServiceStatus:
    """Liveness fact for *name* (`supervisor` or `serve`)."""
    return ServiceRegistry(
        fleet_home if fleet_home is not None else state_paths.fleet_home()
    ).status(name)
