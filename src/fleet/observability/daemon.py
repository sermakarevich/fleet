"""POSIX PID-file daemon manager for fleet's long-lived services (fleet-nbu).

`fleet run` (the supervisor) and `fleet serve` (the UI server) can be managed as
detached background daemons via `start` / `stop` / `restart` / `status`
sub-commands. This module is the engine behind them: it spawns the foreground
entrypoint in a new session, tracks it through a JSON PID file under
``$FLEET_HOME``, and signals it for shutdown.

Scope is deliberately **CLI-managed only**: a daemon started here does *not*
survive a reboot and is *not* auto-restarted if it crashes. Use ``<svc> restart``
to pick up code changes. (For survive-reboot / auto-restart semantics you'd wrap
these foreground entrypoints in a launchd/systemd unit — intentionally out of
scope.)

The module is console-agnostic: methods return small result dataclasses and
raise typed errors, so the CLI layer owns all user-facing echoing.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import fleet
from fleet.core.iso import now_iso
from fleet.core.limits import LOG_ROOT, SHUTDOWN_GRACE_SEC
from fleet.core.process import pid_alive

# Seconds to wait after spawning before probing liveness, so `start` can report
# an immediately-crashing daemon (bad config, import error) instead of a false
# "started" with a pid that is already gone.
STARTUP_PROBE_SEC: float = 0.7


def code_fingerprint(pkg_root: Path | None = None) -> str:
    """SHA1 of all .py files under the fleet package, sorted by path.

    Returns a 12-char hex digest for display and comparison. Catches both
    git pulls (changed content) and local edits (uncommitted changes).
    """
    if pkg_root is None:
        pkg_root = Path(fleet.__file__).parent
    h = hashlib.sha1(usedforsecurity=False)
    for p in sorted(pkg_root.rglob("*.py")):
        h.update(p.as_posix().encode())
        with contextlib.suppress(OSError):
            h.update(p.read_bytes())
    return h.hexdigest()[:12]


# Poll interval while waiting for a signalled process to exit.
_STOP_POLL_SEC: float = 0.1


@dataclass(frozen=True)
class DaemonSpec:
    """Static description of one managed daemon.

    Attributes:
        name: Human label used in messages (e.g. ``"supervisor"``, ``"serve"``).
        pidfile: Absolute path to the JSON PID file.
        logfile: Absolute path the daemon's stdout+stderr are appended to.
        argv: Command to exec — the *foreground* entrypoint of the service.
        cwd: Working directory for the spawned process.
        stop_timeout: Seconds to wait after SIGTERM before escalating to SIGKILL.
        extra: Extra key/values merged into the PID-file JSON (e.g. ``{"port": 7890}``).
    """

    name: str
    pidfile: Path
    logfile: Path
    argv: list[str]
    cwd: Path
    stop_timeout: float
    extra: dict = field(default_factory=dict)


@dataclass
class StartResult:
    pid: int
    already_running: bool
    # False when the startup liveness probe found the process already gone.
    alive: bool


@dataclass
class DaemonStatus:
    running: bool
    pid: int | None
    started_at: str | None
    extra: dict
    version_fingerprint: str | None = None
    stale: bool = False


def read_pidfile(spec: DaemonSpec) -> dict | None:  # noqa: PLR0911
    """Return the parsed PID-file dict, or None if absent/unreadable.

    Tolerates a bare-integer PID file for backward compatibility with the
    ``{pid}`` shape the supervisor route already understands.
    """
    path = spec.pidfile
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not text:
        return None
    try:
        data = json.loads(text)
    except (ValueError, json.JSONDecodeError):
        return {"pid": int(text)} if text.isdigit() else None
    if isinstance(data, dict):
        return data
    if isinstance(data, int):
        return {"pid": data}
    return None


def _pid(spec: DaemonSpec) -> int | None:
    """PID recorded in the pidfile, or None when missing/unparseable."""
    data = read_pidfile(spec)
    if not data:
        return None
    try:
        pid = int(data.get("pid", 0))
    except (TypeError, ValueError):
        return None
    return pid or None


def _is_alive(spec: DaemonSpec) -> bool:
    """True when the pidfile points at a live process."""
    pid = _pid(spec)
    return pid is not None and pid_alive(pid)


def _write_pidfile(spec: DaemonSpec, pid: int) -> None:
    """Record *pid* plus start facts atomically (POSIX rename)."""
    spec.pidfile.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "pid": pid,
        "started_at": now_iso(),
        "version_fingerprint": code_fingerprint(),
        **spec.extra,
    }
    tmp = spec.pidfile.with_name(spec.pidfile.name + ".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    tmp.replace(spec.pidfile)  # atomic on POSIX


def _clear_pidfile(spec: DaemonSpec) -> None:
    """Remove the pidfile, ignoring a missing file."""
    with contextlib.suppress(FileNotFoundError):
        spec.pidfile.unlink()


def status(spec: DaemonSpec) -> DaemonStatus:
    """Report current state, cleaning up a stale PID file as a side effect."""
    data = read_pidfile(spec)
    if not data:
        return DaemonStatus(running=False, pid=None, started_at=None, extra={})
    pid = _pid(spec)
    if pid is None or not pid_alive(pid):
        _clear_pidfile(spec)  # stale
        return DaemonStatus(running=False, pid=None, started_at=None, extra={})
    extra = {k: v for k, v in data.items() if k not in ("pid", "started_at", "version_fingerprint")}
    stored_fp = data.get("version_fingerprint")
    stale = stored_fp is not None and stored_fp != code_fingerprint()
    return DaemonStatus(
        running=True,
        pid=pid,
        started_at=data.get("started_at"),
        extra=extra,
        version_fingerprint=stored_fp,
        stale=stale,
    )


def start(spec: DaemonSpec) -> StartResult:
    """Spawn the daemon detached, write the PID file, probe liveness.

    Idempotent: if a live process is already recorded, returns it with
    ``already_running=True`` without spawning a second one.
    """
    existing = _pid(spec)
    if existing is not None and pid_alive(existing):
        return StartResult(pid=existing, already_running=True, alive=True)

    # Stale or absent PID file — (re)spawn.
    spec.logfile.parent.mkdir(parents=True, exist_ok=True)
    log_fh = open(spec.logfile, "a", encoding="utf-8")  # noqa: SIM115
    try:
        proc = subprocess.Popen(  # noqa: S603
            spec.argv,
            cwd=str(spec.cwd),
            stdin=subprocess.DEVNULL,
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            start_new_session=True,  # detach from controlling terminal
            env=os.environ.copy(),
        )
    finally:
        log_fh.close()  # child keeps its own dup of the fd

    _write_pidfile(spec, proc.pid)

    # Give the child a moment to fail fast (bad config, import error, etc.).
    time.sleep(STARTUP_PROBE_SEC)
    alive = pid_alive(proc.pid)
    if not alive:
        _clear_pidfile(spec)
    return StartResult(pid=proc.pid, already_running=False, alive=alive)


def stop(spec: DaemonSpec, timeout: float | None = None) -> bool:
    """Stop the daemon: SIGTERM, wait, then SIGKILL the process group.

    Returns True if a live process was signalled, False if nothing was
    running (idempotent). Always clears the PID file.
    """
    timeout = spec.stop_timeout if timeout is None else timeout
    pid = _pid(spec)
    if pid is None or not pid_alive(pid):
        _clear_pidfile(spec)
        return False

    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        _clear_pidfile(spec)
        return False

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not pid_alive(pid):
            _clear_pidfile(spec)
            return True
        time.sleep(_STOP_POLL_SEC)

    # Still alive past the grace window — hard-kill the whole session.
    _sigkill(pid)
    _clear_pidfile(spec)
    return True


def _sigkill(pid: int) -> None:
    """SIGKILL the process group (falling back to the pid) without raising."""
    # start_new_session makes the daemon a process-group leader (pgid==pid),
    # so killing the group takes down any child processes it spawned too.
    try:
        os.killpg(os.getpgid(pid), signal.SIGKILL)
        return
    except (ProcessLookupError, PermissionError):
        pass
    with contextlib.suppress(ProcessLookupError):
        os.kill(pid, signal.SIGKILL)


def restart(spec: DaemonSpec, before_start: Callable[[], None] | None = None) -> StartResult:
    """Stop (if running) then start.

    ``before_start`` runs **before** the stop, so an expensive/flaky
    pre-step (e.g. ``make ui-build``) executes against the still-running
    daemon and, if it raises, aborts the restart without taking the daemon
    down. Exceptions from ``before_start`` propagate to the caller.
    """
    if before_start is not None:
        before_start()
    stop(spec)
    return start(spec)


def python_module_argv(*args: str) -> list[str]:
    """Build an argv that re-execs this interpreter as ``python -m fleet ...``."""
    return [sys.executable, "-m", "fleet", *args]


def _log_dir(fleet_home: Path) -> Path:

    log_root = Path(LOG_ROOT)
    return log_root if log_root.is_absolute() else fleet_home / log_root


def supervisor_spec(fleet_home: Path) -> DaemonSpec:
    """Daemon spec for `fleet run`, shared by the CLI and the /api/supervisor route.

    PID file is `$FLEET_HOME/.supervisor.pid` so the UI's /api/supervisor route
    lights up. stop_timeout exceeds SHUTDOWN_GRACE_SEC so the supervisor's
    graceful shutdown (releasing in-flight tasks) completes before any SIGKILL.
    """

    return DaemonSpec(
        name="supervisor",
        pidfile=fleet_home / ".supervisor.pid",
        logfile=_log_dir(fleet_home) / "supervisor.daemon.log",
        argv=python_module_argv("run", "foreground"),
        cwd=fleet_home,
        stop_timeout=float(SHUTDOWN_GRACE_SEC + 5),
        extra={},
    )


def serve_spec(fleet_home: Path, host: str, port: int) -> DaemonSpec:
    """Daemon spec for `fleet serve`. Stores host/port so `restart` can reuse them."""
    return DaemonSpec(
        name="serve",
        pidfile=fleet_home / ".serve.pid",
        logfile=_log_dir(fleet_home) / "serve.daemon.log",
        argv=python_module_argv("serve", "foreground", "--host", host, "--port", str(port)),
        cwd=fleet_home,
        stop_timeout=10.0,
        extra={"port": port, "host": host},
    )
