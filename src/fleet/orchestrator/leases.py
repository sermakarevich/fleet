"""Claim-lease reconciliation: reclaim attempts whose heartbeat stopped.

A claim (`bd update --claim`) is static, so a runner that dies without
reaping (asyncio crash, host sleep) would leave its bead `in_progress`
forever. Every running attempt therefore holds a *lease*: while the
coder subprocess lives, `workers/llm_session.py` rewrites
`attempts/<n>/run.json` every `HEARTBEAT_SEC` with `heartbeat_at` and
`lease_until = now + 3 * HEARTBEAT_SEC`, plus the `pid`, `host`, and
`supervisor_pid` that own it.

`LeasesMixin.reconcile_leases` runs at supervisor startup and every
`LEASE_RECONCILE_INTERVAL_SEC` from the status loop. It reclaims a bead
only when ALL hold: the lease is past by more than one full heartbeat,
the task is not in this supervisor's in-memory running set, and the
recorded pid is dead (or the host differs from this one). A stale lease
with a live pid only logs `lease_stale_pid_alive` — fleet never kills
what it cannot prove is its own. Beads with no attempt dir / no run.json
(human-claimed via `bd update --claim`) are never touched.

Reclaim journals `record_end(outcome="killed", reason="lease expired")`
and releases through the normal queue path; the claim loop picks the
bead up later. Nothing here re-spawns work directly.
"""

from __future__ import annotations

import json
import os
import socket
from datetime import UTC, datetime

from fleet.core.limits import HEARTBEAT_SEC
from fleet.state.attempts import latest_attempt_dir, load_attempts, record_end
from fleet.state.paths import task_dir as _task_dir
from fleet.state.validation_marker import needs_validation

from . import worktree

LEASE_EXPIRED_REASON = "lease expired"


def _parse_ts(value: object) -> datetime | None:
    """Parse an ISO timestamp, or None when missing/malformed/naive-guarded."""
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def _pid_alive(pid: object) -> bool:
    """True when *pid* names a live process (signal 0 probe)."""
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    except OSError:
        return False
    return True


def _host_name() -> str:
    """This machine's hostname for lease ownership checks (best effort)."""
    try:
        return socket.gethostname()
    except OSError:
        return "unknown"


def lease_is_stale(lease_until: datetime | None, now: datetime | None = None) -> bool:
    """True when *lease_until* is past by more than one full heartbeat.

    The extra heartbeat of slack absorbs one slow event-loop tick, so a
    live worker is never mistaken for dead. A missing lease is never
    stale: without heartbeat keys we cannot prove anything.
    """
    if lease_until is None:
        return False
    at = now or datetime.now(tz=UTC)
    return (at - lease_until).total_seconds() > HEARTBEAT_SEC


class LeasesMixin:
    def _sweep_orphan_worktrees(self) -> None:
        """Remove worktrees with no corresponding active task (startup sweep)."""
        worktrees_dir = worktree.worktree_path("")
        if not worktrees_dir.is_dir():
            return

        fleet_home = worktrees_dir.parent

        for worktree_dir in worktrees_dir.iterdir():
            if not worktree_dir.is_dir():
                continue

            task_id = worktree_dir.name

            if task_id in self.in_flight:
                continue

            task_dir = _task_dir(fleet_home, task_id)
            if needs_validation(task_dir):
                continue

            self._log.info("worktree.sweep.removed", task_id=task_id)
            worktree.remove_worktree(self._project_root, task_id)

    def _log_lease_once(self, event: str, task_id: str, **fields) -> None:
        """Log a recurring lease notice only the first time per task."""
        logged = getattr(self, "_lease_logged", None)
        if logged is None:
            self._lease_logged = logged = set()
        key = f"{event}:{task_id}"
        if key in logged:
            return
        logged.add(key)
        self._log.info(event, task_id=task_id, **fields)

    def reconcile_leases(self) -> None:
        """Release `in_progress` beads whose lease expired on a dead attempt.

        Called once at supervisor startup and periodically from the status
        loop. Never raises: per-task handling is guarded so one corrupt
        task directory cannot stall reconciliation of the rest.
        """
        try:
            in_progress = self._queue.list_in_progress(limit=500)
        except Exception as exc:
            self._log.warning("reconcile_list_failed", error=str(exc))
            return
        for task in in_progress:
            if task.id in self.in_flight:
                continue
            try:
                self._reconcile_one_lease(task)
            except Exception as exc:  # noqa: BLE001 - one bad task must not stop the sweep
                self._log.warning(
                    "lease_reconcile_failed", task_id=task.id, error=str(exc)
                )

    def _reconcile_one_lease(self, task) -> None:
        """Reclaim *task* iff its lease is stale on a provably dead attempt."""
        task_dir = self._task_dir_for(task)
        attempt_dir = latest_attempt_dir(task_dir)
        if attempt_dir is None:
            # Claimed by a human (`bd update --claim`) or never spawned:
            # there is no attempt to own, so there is nothing to reclaim.
            self._log_lease_once("lease_no_attempt_dir", task.id)
            return
        run_file = attempt_dir / "run.json"
        try:
            data = json.loads(run_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self._log_lease_once("lease_no_run_json", task.id)
            return
        if not isinstance(data, dict):
            self._log_lease_once("lease_no_run_json", task.id)
            return
        lease_until = _parse_ts(data.get("lease_until"))
        if lease_until is None:
            # No heartbeat was ever written (old attempt format): without
            # lease keys we cannot prove anything, so never touch it.
            self._log_lease_once("lease_no_heartbeat", task.id)
            return
        if not lease_is_stale(lease_until):
            return
        pid = data.get("pid")
        if not isinstance(pid, int) or isinstance(pid, bool):
            self._log.warning("lease_no_pid", task_id=task.id)
            return
        host = data.get("host")
        if isinstance(host, str) and host and host != _host_name():
            pid_dead = True
        else:
            pid_dead = not _pid_alive(pid)
        if not pid_dead:
            # Stale lease but the process is alive: it may be a slow host
            # or a pid another supervisor owns. Never kill; just warn.
            self._log.warning(
                "lease_stale_pid_alive",
                task_id=task.id,
                pid=pid,
                lease_until=lease_until.isoformat(),
            )
            return
        history = load_attempts(task_dir)
        if history and history[-1].get("ended_at") is not None:
            # The attempt already journaled its end (reap ran and the queue
            # path owns the bead now): reclaiming again would corrupt the
            # recorded outcome and double-release.
            return
        try:
            record_end(
                task_dir,
                outcome="killed",
                exit_code=None,
                reason=LEASE_EXPIRED_REASON,
                action="release",
            )
        except OSError as exc:
            self._log.warning("lease_record_failed", task_id=task.id, error=str(exc))
            return
        try:
            self._queue.release(task.id, reason="lease expired; re-queued")
            self._log.warning(
                "lease_expired_released", task_id=task.id, pid=pid
            )
        except Exception as exc:
            self._log.warning(
                "lease_release_failed", task_id=task.id, error=str(exc)
            )
