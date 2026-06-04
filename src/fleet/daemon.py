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

import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

# Seconds to wait after spawning before probing liveness, so `start` can report
# an immediately-crashing daemon (bad config, import error) instead of a false
# "started" with a pid that is already gone.
STARTUP_PROBE_SEC: float = 0.7

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


def _pid_alive(pid: int) -> bool:
    """Return True if `pid` names a live process (signal 0 probe)."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Exists but owned by another user — still "alive" for our purposes.
        return True
    return True


class Daemon:
    """Manage a single :class:`DaemonSpec` via its PID file."""

    def __init__(self, spec: DaemonSpec) -> None:
        self.spec = spec

    # -- PID file -----------------------------------------------------------

    def read_pidfile(self) -> dict | None:
        """Return the parsed PID-file dict, or None if absent/unreadable.

        Tolerates a bare-integer PID file for backward compatibility with the
        ``{pid}`` shape the supervisor route already understands.
        """
        path = self.spec.pidfile
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

    def pid(self) -> int | None:
        data = self.read_pidfile()
        if not data:
            return None
        try:
            pid = int(data.get("pid", 0))
        except (TypeError, ValueError):
            return None
        return pid or None

    def is_alive(self) -> bool:
        pid = self.pid()
        return pid is not None and _pid_alive(pid)

    def _write_pidfile(self, pid: int) -> None:
        self.spec.pidfile.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "pid": pid,
            "started_at": datetime.now(timezone.utc).isoformat(),
            **self.spec.extra,
        }
        tmp = self.spec.pidfile.with_name(self.spec.pidfile.name + ".tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        tmp.replace(self.spec.pidfile)  # atomic on POSIX

    def _clear_pidfile(self) -> None:
        try:
            self.spec.pidfile.unlink()
        except FileNotFoundError:
            pass

    # -- lifecycle ----------------------------------------------------------

    def status(self) -> DaemonStatus:
        """Report current state, cleaning up a stale PID file as a side effect."""
        data = self.read_pidfile()
        if not data:
            return DaemonStatus(running=False, pid=None, started_at=None, extra={})
        pid = self.pid()
        if pid is None or not _pid_alive(pid):
            self._clear_pidfile()  # stale
            return DaemonStatus(running=False, pid=None, started_at=None, extra={})
        extra = {k: v for k, v in data.items() if k not in ("pid", "started_at")}
        return DaemonStatus(
            running=True,
            pid=pid,
            started_at=data.get("started_at"),
            extra=extra,
        )

    def start(self) -> StartResult:
        """Spawn the daemon detached, write the PID file, probe liveness.

        Idempotent: if a live process is already recorded, returns it with
        ``already_running=True`` without spawning a second one.
        """
        existing = self.pid()
        if existing is not None and _pid_alive(existing):
            return StartResult(pid=existing, already_running=True, alive=True)

        # Stale or absent PID file — (re)spawn.
        self.spec.logfile.parent.mkdir(parents=True, exist_ok=True)
        log_fh = open(self.spec.logfile, "a", encoding="utf-8")  # noqa: SIM115
        try:
            proc = subprocess.Popen(  # noqa: S603
                self.spec.argv,
                cwd=str(self.spec.cwd),
                stdin=subprocess.DEVNULL,
                stdout=log_fh,
                stderr=subprocess.STDOUT,
                start_new_session=True,  # detach from controlling terminal
                env=os.environ.copy(),
            )
        finally:
            log_fh.close()  # child keeps its own dup of the fd

        self._write_pidfile(proc.pid)

        # Give the child a moment to fail fast (bad config, import error, etc.).
        time.sleep(STARTUP_PROBE_SEC)
        alive = _pid_alive(proc.pid)
        if not alive:
            self._clear_pidfile()
        return StartResult(pid=proc.pid, already_running=False, alive=alive)

    def stop(self, timeout: float | None = None) -> bool:
        """Stop the daemon: SIGTERM, wait, then SIGKILL the process group.

        Returns True if a live process was signalled, False if nothing was
        running (idempotent). Always clears the PID file.
        """
        timeout = self.spec.stop_timeout if timeout is None else timeout
        pid = self.pid()
        if pid is None or not _pid_alive(pid):
            self._clear_pidfile()
            return False

        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            self._clear_pidfile()
            return False

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not _pid_alive(pid):
                self._clear_pidfile()
                return True
            time.sleep(_STOP_POLL_SEC)

        # Still alive past the grace window — hard-kill the whole session.
        self._sigkill(pid)
        self._clear_pidfile()
        return True

    @staticmethod
    def _sigkill(pid: int) -> None:
        # start_new_session makes the daemon a process-group leader (pgid==pid),
        # so killing the group takes down any child processes it spawned too.
        try:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
            return
        except (ProcessLookupError, PermissionError):
            pass
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    def restart(self, before_start: Callable[[], None] | None = None) -> StartResult:
        """Stop (if running) then start.

        ``before_start`` runs **before** the stop, so an expensive/flaky
        pre-step (e.g. ``make ui-build``) executes against the still-running
        daemon and, if it raises, aborts the restart without taking the daemon
        down. Exceptions from ``before_start`` propagate to the caller.
        """
        if before_start is not None:
            before_start()
        self.stop()
        return self.start()


def python_module_argv(*args: str) -> list[str]:
    """Build an argv that re-execs this interpreter as ``python -m fleet ...``."""
    return [sys.executable, "-m", "fleet", *args]
