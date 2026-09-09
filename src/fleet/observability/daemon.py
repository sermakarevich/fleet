"""POSIX PID-file daemon manager for fleet's long-lived services (fleet-nbu).

`fleet run` (the supervisor) and `fleet serve` (the UI server) can be managed as
detached background daemons via `start` / `stop` / `restart` / `status`
sub-commands. This module is the engine behind them: it spawns the foreground
entrypoint in a new session, tracks it through a PID file under
``$FLEET_HOME`` (owned by ``observability/pidfile.py``), and signals it for
shutdown.

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
import functools
import hashlib
import os
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO

import fleet
from fleet.core.iso import now_iso
from fleet.core.limits import LOG_ROTATE_BYTES, LOG_ROTATE_KEEP, SHUTDOWN_GRACE_SEC
from fleet.core.process import pid_alive
from fleet.state.atomic import rotate_overgrown
from fleet.state.paths import log_dir

from . import pidfile
from .pidfile import PidFile

# Startup liveness window: after spawning, the child is probed every
# _STARTUP_POLL_SEC for STARTUP_WINDOW_SEC. A single early probe reports
# success for a daemon that dies a second later (bad config, import error),
# so start() only reports alive when the child survives the whole window.
STARTUP_WINDOW_SEC: float = 3.0
_STARTUP_POLL_SEC: float = 0.25

# A start lock older than this is treated as stale (a previous start that
# crashed mid-window) and cleared; a fresher lock means a concurrent start
# is in flight. Well above STARTUP_WINDOW_SEC so a live start never looks stale.
_LOCK_STALE_SEC: float = 30.0

# Poll interval while waiting for a signalled process to exit.
_STOP_POLL_SEC: float = 0.1


@functools.lru_cache
def _hash_package(root: str) -> str:
    """SHA1 of all .py files under *root*, sorted by path (12-char hex)."""
    h = hashlib.sha1(usedforsecurity=False)
    for p in sorted(Path(root).rglob("*.py")):
        h.update(p.as_posix().encode())
        with contextlib.suppress(OSError):
            h.update(p.read_bytes())
    return h.hexdigest()[:12]


def code_fingerprint(pkg_root: Path | None = None) -> str:
    """Short hash of the fleet package source, memoised for the process lifetime.

    The fingerprint names the code *this process* loaded: module imports are
    cached in ``sys.modules``, so files edited after startup never change what
    a running daemon executes. Re-hashing hundreds of files on every
    ``status()`` call is pure waste — the value only changes across a process
    restart, which is exactly when the cache dies with the process.
    """
    if pkg_root is None:
        pkg_root = Path(fleet.__file__).parent
    return _hash_package(str(pkg_root))


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
    pid: int = 0
    already_running: bool = False
    # False when the startup liveness probe found the process already gone,
    # when another start holds the lock, or when spawning failed outright.
    alive: bool = False
    # Human detail for the failure modes above ("" on a clean start).
    detail: str = ""


@dataclass
class DaemonStatus:
    running: bool
    pid: int | None
    started_at: str | None
    extra: dict
    version_fingerprint: str | None = None
    stale: bool = False


def _pid(spec: DaemonSpec) -> int | None:
    """PID recorded in the pidfile, or None when missing/unparseable."""
    record = pidfile.read(spec.pidfile)
    return record.pid if record is not None else None


def _is_alive(spec: DaemonSpec) -> bool:
    """True when the pidfile points at a live process."""
    pid = _pid(spec)
    return pid is not None and pid_alive(pid)


def _record_pid(spec: DaemonSpec, pid: int) -> None:
    """Write the pidfile record for a freshly spawned daemon."""
    spec.pidfile.parent.mkdir(parents=True, exist_ok=True)
    pidfile.write(
        spec.pidfile,
        PidFile(
            pid=pid,
            started_at=now_iso(),
            fingerprint=code_fingerprint(),
            extra=dict(spec.extra),
        ),
    )


def _clear_pidfile(spec: DaemonSpec) -> None:
    """Remove the pidfile, ignoring a missing file."""
    with contextlib.suppress(FileNotFoundError):
        spec.pidfile.unlink()


def status(spec: DaemonSpec) -> DaemonStatus:
    """Report current state, cleaning up a stale PID file as a side effect."""
    record = pidfile.read(spec.pidfile)
    if record is None:
        return DaemonStatus(running=False, pid=None, started_at=None, extra={})
    if not pid_alive(record.pid):
        _clear_pidfile(spec)  # stale
        return DaemonStatus(running=False, pid=None, started_at=None, extra={})
    stale = record.fingerprint is not None and record.fingerprint != code_fingerprint()
    return DaemonStatus(
        running=True,
        pid=record.pid,
        started_at=record.started_at,
        extra=dict(record.extra),
        version_fingerprint=record.fingerprint,
        stale=stale,
    )


def _lock_path(spec: DaemonSpec) -> Path:
    """The start lock beside the pidfile, held for the duration of start()."""
    return spec.pidfile.parent / (spec.name + ".lock")


def _lock_is_stale(lock: Path) -> bool:
    """True when the lock predates any start that could still be in flight."""
    try:
        age = time.time() - lock.stat().st_mtime
    except OSError:
        return False
    return age > _LOCK_STALE_SEC


def _try_acquire(lock: Path) -> int | None:
    """Atomically create the lock, returning its fd (None when held by another start)."""
    try:
        return os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        pass
    if not _lock_is_stale(lock):
        return None
    with contextlib.suppress(OSError):
        lock.unlink()
    try:
        return os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return None


def _release_lock(fd: int, lock: Path) -> None:
    """Close and remove a lock this process created."""
    with contextlib.suppress(OSError):
        os.close(fd)
    with contextlib.suppress(OSError):
        lock.unlink()


def _already_running(pid: int | None) -> StartResult:
    """The typed outcome when a live daemon (or a concurrent start) owns the name."""
    return StartResult(pid=pid or 0, already_running=True, alive=False, detail="already running")


def _open_log(path: Path) -> IO[str]:
    """Append handle to the daemon log, rotating first when over budget."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rotate_overgrown(path, max_bytes=LOG_ROTATE_BYTES, keep=LOG_ROTATE_KEEP)
    return open(path, "a", encoding="utf-8")  # noqa: SIM115


def _spawn_child(spec: DaemonSpec, log_fh: IO[str]) -> subprocess.Popen:
    """Fork the detached child; Popen errors propagate to the caller."""
    return subprocess.Popen(  # noqa: S603
        spec.argv,
        cwd=str(spec.cwd),
        stdin=subprocess.DEVNULL,
        stdout=log_fh,
        stderr=subprocess.STDOUT,
        start_new_session=True,  # detach from controlling terminal
        env=os.environ.copy(),
    )


def _probe_liveness(pid: int) -> bool:
    """True when *pid* survives the whole startup window (polled each step)."""
    probes = max(1, int(STARTUP_WINDOW_SEC / _STARTUP_POLL_SEC))
    for _ in range(probes):
        time.sleep(_STARTUP_POLL_SEC)
        if not pid_alive(pid):
            return False
    return True


def _spawn_and_probe(spec: DaemonSpec) -> StartResult:
    """Spawn the child, record it, and report whether it survived startup."""
    log_fh = _open_log(spec.logfile)
    try:
        proc = _spawn_child(spec, log_fh)
    except Exception as exc:
        return StartResult(pid=0, already_running=False, alive=False, detail=str(exc))
    finally:
        log_fh.close()  # child keeps its own dup of the fd

    _record_pid(spec, proc.pid)
    if not _probe_liveness(proc.pid):
        _clear_pidfile(spec)
        return StartResult(
            pid=proc.pid,
            already_running=False,
            alive=False,
            detail="process exited during startup",
        )
    return StartResult(pid=proc.pid, already_running=False, alive=True)


def start(spec: DaemonSpec) -> StartResult:
    """Spawn the daemon detached, write the PID file, probe liveness.

    Idempotent: if a live process is already recorded, or another start
    holds the lock, returns ``already running`` without spawning a second
    one. A spawn failure becomes ``StartResult(alive=False)``, never a raw
    ``Popen`` exception.
    """
    existing = _pid(spec)
    if existing is not None and pid_alive(existing):
        return _already_running(existing)

    # Stale or absent PID file — (re)spawn under the start lock.
    spec.pidfile.parent.mkdir(parents=True, exist_ok=True)
    lock = _lock_path(spec)
    fd = _try_acquire(lock)
    if fd is None:
        return _already_running(_pid(spec))
    try:
        return _spawn_and_probe(spec)
    finally:
        _release_lock(fd, lock)


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


def supervisor_spec(fleet_home: Path) -> DaemonSpec:
    """Daemon spec for `fleet run`, shared by the CLI and the /api/supervisor route.

    PID file is `$FLEET_HOME/.supervisor.pid` so the UI's /api/supervisor route
    lights up. stop_timeout exceeds SHUTDOWN_GRACE_SEC so the supervisor's
    graceful shutdown (releasing in-flight tasks) completes before any SIGKILL.
    """

    return DaemonSpec(
        name="supervisor",
        pidfile=fleet_home / ".supervisor.pid",
        logfile=log_dir(fleet_home) / "supervisor.daemon.log",
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
        logfile=log_dir(fleet_home) / "serve.daemon.log",
        argv=python_module_argv("serve", "foreground", "--host", host, "--port", str(port)),
        cwd=fleet_home,
        stop_timeout=10.0,
        extra={"port": port, "host": host},
    )


#: PID-file name for the ollama SSH tunnel (shared with the status reader
#: in observability/process.py so both sides track the same file).
TUNNEL_PIDFILE_NAME = ".ollama_tunnel.pid"


def tunnel_spec(
    fleet_home: Path,
    argv: list[str],
    *,
    local_port: int = 0,
    ssh_host: str = "",
    remote_port: int = 0,
) -> DaemonSpec:
    """Daemon spec for the ollama SSH tunnel forward.

    ``argv`` is the foreground ``ssh -N`` holding the forward (built by
    ``integrations/ollama_tunnel.py``); the spec only adds fleet's daemon
    bookkeeping. Stores the forward facts so ``status`` can report them.
    Callers that only need the pidfile (stop after a config change) pass
    ``argv=[]`` — stop never execs it.
    """
    return DaemonSpec(
        name="ollama-tunnel",
        pidfile=fleet_home / TUNNEL_PIDFILE_NAME,
        logfile=log_dir(fleet_home) / "ollama_tunnel.daemon.log",
        argv=argv,
        cwd=fleet_home,
        stop_timeout=10.0,
        extra={"port": local_port, "host": ssh_host, "remote_port": remote_port},
    )


__all__ = [
    "DaemonSpec",
    "DaemonStatus",
    "STARTUP_WINDOW_SEC",
    "TUNNEL_PIDFILE_NAME",
    "StartResult",
    "code_fingerprint",
    "python_module_argv",
    "restart",
    "serve_spec",
    "start",
    "status",
    "stop",
    "supervisor_spec",
    "tunnel_spec",
]
