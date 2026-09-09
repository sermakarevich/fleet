"""Claim-lease reconciliation: reclaim attempts whose heartbeat stopped.

A claim (`bd update --claim`) is static, so a runner that dies without
reaping (asyncio crash, host sleep) would leave its bead `in_progress`
forever. Every running attempt therefore holds a *lease*: while the
coder subprocess lives, `workers/llm_session.py` rewrites
`attempts/<n>/run.json` every `HEARTBEAT_SEC` with `heartbeat_at` and
`lease_until = now + 3 * HEARTBEAT_SEC`, plus the `pid`, `host`, and
`supervisor_pid` that own it.

`reconcile_leases` runs at supervisor startup (via `LeaseReconcile`) and
on its own cadence. It reclaims a bead only when ALL hold: the lease is
past by more than one full heartbeat, the task is not in this
supervisor's in-memory running set, and the recorded pid is dead (or the
host differs from this one). A stale lease with a live pid only logs
`lease_stale_pid_alive` — fleet never kills what it cannot prove is its
own. Beads with no attempt dir / no run.json (human-claimed via
`bd update --claim`) are never touched.

Reclaim journals `record_end(outcome="killed", reason="lease expired")`
and releases through the normal queue path; the claim loop picks the
bead up later. Nothing here re-spawns work directly.
"""

from __future__ import annotations

import contextlib
import json
import shutil
import socket
import subprocess
from datetime import UTC, datetime
from pathlib import Path as _Path
from typing import TYPE_CHECKING

from fleet.core.iso import parse_iso
from fleet.core.limits import HEARTBEAT_SEC, LEASE_RECONCILE_INTERVAL_SEC
from fleet.core.process import pid_alive
from fleet.core.retry_policy import Action
from fleet.core.task import TaskOutcome
from fleet.state.attempts import latest_attempt_dir, load_attempts, record_end
from fleet.state.paths import task_dir as _task_dir
from fleet.state.paths import tasks_root as _tasks_root
from fleet.state.run_file import RunRecord
from fleet.state.validation_marker import needs_validation

from . import worktree
from .service import ServiceOrder, run_periodic

if TYPE_CHECKING:
    from fleet.core.task import Task

    from .state import SupervisorState

LEASE_EXPIRED_REASON = "lease expired"


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


def _remove_orphan_dir(path) -> None:
    """Remove one orphan worktree dir, git-aware when possible.

    Prefers `git worktree remove` via the worktree's own common dir so the
    admin metadata is cleaned; falls back to a plain recursive delete when
    the repo is gone (best effort, never raises).
    """

    target = _Path(path)
    try:
        result = subprocess.run(
            ["git", "-C", str(target), "rev-parse", "--git-common-dir"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            common = _Path(result.stdout.strip())
            repo = common if common.is_absolute() else (target / common)
            rm = subprocess.run(
                ["git", "-C", str(repo), "worktree", "remove", "--force", str(target)],
                capture_output=True,
                text=True,
                check=False,
            )
            if rm.returncode == 0:
                return
    except (OSError, subprocess.SubprocessError):
        pass
    with contextlib.suppress(Exception):
        shutil.rmtree(target, ignore_errors=True)


def _task_names(tasks_root) -> list[str]:
    """Task dir names under *tasks_root* (best effort, never raises)."""
    try:
        if tasks_root.is_dir():
            return [p.name for p in tasks_root.iterdir() if p.is_dir()]
    except OSError:
        pass
    return []


def sweep_orphan_worktrees(st: SupervisorState) -> None:
    """Remove worktrees with no corresponding active task (startup sweep)."""

    worktrees_dir = worktree.worktrees_root(st.fleet_home)
    if not worktrees_dir.is_dir():
        return
    tasks_root = _tasks_root(st.fleet_home)
    names = _task_names(tasks_root)

    # Worktree dirs still in use: every task.json worktree_path. Tasks
    # awaiting validation keep their dirs via the same rule (their
    # task.json still points at the worktree until the merge lands).
    live: set[str] = set()
    for task_dir in [tasks_root / n for n in names]:
        try:
            meta = json.loads((task_dir / "task.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            meta = {}
        wt = meta.get("worktree_path") if isinstance(meta, dict) else None
        if wt:
            with contextlib.suppress(OSError):
                live.add(str(_Path(wt).resolve()))

    for worktree_dir in worktrees_dir.iterdir():
        if not worktree_dir.is_dir():
            continue
        try:
            resolved = str(worktree_dir.resolve())
        except OSError:
            continue
        if resolved in live:
            continue
        # Name-based keep: legacy dirs named exactly <task_id>, and new
        # <repo>-<task_id> dirs, survive while validating or in flight.
        # The repo prefix is unknown here, so a "<repo>-<task>" dir
        # matches task "<task>" by suffix.
        task_id = worktree_dir.name
        matched = [n for n in names if task_id == n or task_id.endswith(f"-{n}")]
        keep = any(task_id == tid or task_id.endswith(f"-{tid}") for tid in st.running)
        if not keep:
            for cand in [task_id, *matched]:
                try:
                    if needs_validation(_task_dir(st.fleet_home, cand)):
                        keep = True
                        break
                except OSError:
                    continue
        if keep:
            continue
        st.log.info("worktree.sweep.removed", task_id=task_id)
        _remove_orphan_dir(worktree_dir)


def _log_lease_once(
    seen: set[str], st: SupervisorState, event: str, task_id: str, **fields
) -> None:
    """Log a recurring lease notice only the first time per task."""
    key = f"{event}:{task_id}"
    if key in seen:
        return
    seen.add(key)
    st.log.info(event, task_id=task_id, **fields)


def reconcile_leases(st: SupervisorState, seen: set[str] | None = None) -> None:
    """Release `in_progress` beads whose lease expired on a dead attempt.

    Called once at supervisor startup and periodically by LeaseReconcile.
    Never raises: per-task handling is guarded so one corrupt task
    directory cannot stall reconciliation of the rest.
    """
    dedupe = seen if seen is not None else set()
    try:
        in_progress = st.queue.list_in_progress(limit=500)
    except Exception as exc:
        st.log.warning("reconcile_list_failed", error=str(exc))
        return
    for task in in_progress:
        if task.id in st.running:
            continue
        try:
            _reconcile_one_lease(st, task, dedupe)
        except Exception as exc:  # noqa: BLE001 - one bad task must not stop the sweep
            st.log.warning("lease_reconcile_failed", task_id=task.id, error=str(exc))


def _reconcile_one_lease(  # noqa: PLR0911  # ADR 0006 bead 20
    st: SupervisorState, task: Task, seen: set[str]
) -> None:
    """Reclaim *task* iff its lease is stale on a provably dead attempt."""
    task_dir = st.task_dir_for(task.id)
    attempt_dir = latest_attempt_dir(task_dir)
    if attempt_dir is None:
        # Claimed by a human (`bd update --claim`) or never spawned:
        # there is no attempt to own, so there is nothing to reclaim.
        _log_lease_once(seen, st, "lease_no_attempt_dir", task.id)
        return
    run = RunRecord.load(attempt_dir)
    if run is None:
        _log_lease_once(seen, st, "lease_no_run_json", task.id)
        return
    lease_until = parse_iso(run.lease_until)
    if lease_until is None:
        # No heartbeat was ever written (old attempt format): without
        # lease keys we cannot prove anything, so never touch it.
        _log_lease_once(seen, st, "lease_no_heartbeat", task.id)
        return
    if not lease_is_stale(lease_until):
        return
    pid = run.pid
    if not isinstance(pid, int) or isinstance(pid, bool):
        st.log.warning("lease_no_pid", task_id=task.id)
        return
    host = run.host
    if isinstance(host, str) and host and host != _host_name():
        pid_dead = True
    else:
        pid_dead = not pid_alive(pid)
    if not pid_dead:
        # Stale lease but the process is alive: it may be a slow host
        # or a pid another supervisor owns. Never kill; just warn.
        st.log.warning(
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
            outcome=TaskOutcome.KILLED,
            exit_code=None,
            reason=LEASE_EXPIRED_REASON,
            action=Action.RELEASE,
        )
    except OSError as exc:
        st.log.warning("lease_record_failed", task_id=task.id, error=str(exc))
        return
    try:
        st.queue.release(task.id, reason="lease expired; re-queued")
        st.log.warning("lease_expired_released", task_id=task.id, pid=pid)
    except Exception as exc:
        st.log.warning("lease_release_failed", task_id=task.id, error=str(exc))


class LeaseReconcile:
    """Reclaim dead leases on start and then on the lease cadence."""

    order = ServiceOrder.Leases
    name = "lease_reconcile"

    def __init__(self, interval_sec: float | None = None) -> None:
        self.interval_sec = (
            interval_sec if interval_sec is not None else LEASE_RECONCILE_INTERVAL_SEC
        )
        self._lease_logged: set[str] = set()

    async def on_start(self, st: SupervisorState) -> None:
        """Sweep orphan worktrees, then reclaim dead leases once."""
        sweep_orphan_worktrees(st)
        reconcile_leases(st, self._lease_logged)

    async def tick(self, st: SupervisorState) -> None:
        """Reclaim dead leases."""
        reconcile_leases(st, self._lease_logged)

    async def serve(self, st: SupervisorState) -> None:
        """Tick on the lease cadence until shutdown (shared periodic loop)."""
        await run_periodic(self.name, self.interval_sec, self.tick, st)
