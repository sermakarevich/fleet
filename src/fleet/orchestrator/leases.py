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

The policy is pure in ``core/leases.py`` (``classify_lease``,
``orphan_dirs``); this module only reads, classifies, and acts.
"""

from __future__ import annotations

import contextlib
import json
import shutil
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

from fleet.core.clock import SystemClock
from fleet.core.iso import parse_iso
from fleet.core.leases import LeaseVerdict, classify_lease, orphan_dirs
from fleet.core.limits import HEARTBEAT_SEC, LEASE_RECONCILE_INTERVAL_SEC
from fleet.core.process import host_name, pid_alive
from fleet.core.retry_policy import Action
from fleet.core.task import TaskOutcome
from fleet.state import paths as state_paths
from fleet.state.attempts import latest_attempt_dir, load_attempts, record_end
from fleet.state.run_file import RunRecord
from fleet.state.validation_marker import needs_validation

from . import worktree
from .git import GitRepo
from .service import ServiceOrder, run_periodic

if TYPE_CHECKING:
    from fleet.core.task import Task

    from .state import SupervisorState

LEASE_EXPIRED_REASON = "lease expired"


class _LeaseGap(StrEnum):
    """Why a lease cannot be proven: what the read step failed to find."""

    NONE = "none"
    NO_ATTEMPT_DIR = "lease_no_attempt_dir"
    NO_RUN = "lease_no_run_json"
    NO_HEARTBEAT = "lease_no_heartbeat"
    NO_PID = "lease_no_pid"


@dataclass(frozen=True, slots=True)
class _LeaseFacts:
    """Pre-read facts for one lease; ``classify_lease`` turns them into a verdict."""

    gap: _LeaseGap
    stale: bool
    pid_valid: bool
    pid_dead: bool
    attempt_ended: bool
    lease_until_iso: str
    pid: int


def lease_is_stale(lease_until: datetime | None, now: datetime | None = None) -> bool:
    """True when *lease_until* is past by more than one full heartbeat.

    The extra heartbeat of slack absorbs one slow event-loop tick, so a
    live worker is never mistaken for dead. A missing lease is never
    stale: without heartbeat keys we cannot prove anything.
    """
    if lease_until is None:
        return False
    at = now if now is not None else SystemClock().now()
    return (at - lease_until).total_seconds() > HEARTBEAT_SEC


def _remove_orphan_dir(path: Path) -> None:
    """Remove one orphan worktree dir, git-aware when possible.

    Prefers `git worktree remove` via the worktree's own common dir so the
    admin metadata is cleaned; falls back to a plain recursive delete when
    the repo is gone (best effort, never raises).
    """
    target = Path(path)
    repo = GitRepo(target)
    common = repo.run("rev-parse", "--git-common-dir")
    if common.returncode == 0 and common.stdout.strip():
        admin = Path(common.stdout.strip())
        base = admin if admin.is_absolute() else (target / admin)
        if GitRepo(base).run("worktree", "remove", "--force", str(target)).returncode == 0:
            return
    with contextlib.suppress(Exception):
        shutil.rmtree(target, ignore_errors=True)


def _live_worktree_paths(tasks_root: Path) -> set[str]:
    """Resolved task.json worktree_path values still referencing a worktree."""
    live: set[str] = set()
    try:
        names = [p.name for p in tasks_root.iterdir() if p.is_dir()]
    except OSError:
        return live
    for task_dir in [tasks_root / n for n in names]:
        try:
            meta = json.loads((task_dir / "task.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        wt = meta.get("worktree_path") if isinstance(meta, dict) else None
        if wt:
            with contextlib.suppress(OSError):
                live.add(str(Path(wt).resolve()))
    return live


def _validating_ids(tasks_root: Path) -> set[str]:
    """Task ids whose merge is still awaiting validation (their dirs stay)."""
    ids: set[str] = set()
    try:
        candidates = [p for p in tasks_root.iterdir() if p.is_dir()]
    except OSError:
        return ids
    for task_dir in candidates:
        with contextlib.suppress(OSError):
            if needs_validation(task_dir):
                ids.add(task_dir.name)
    return ids


def sweep_orphan_worktrees(st: SupervisorState) -> None:
    """Remove worktrees with no corresponding active task (startup sweep)."""
    worktrees_dir = worktree.worktrees_root(st.fleet_home)
    if not worktrees_dir.is_dir():
        return
    tasks_root = state_paths.tasks_root(st.fleet_home)
    live_ids = set(st.running) | _validating_ids(tasks_root)
    resolved = _resolved_worktree_dirs(worktrees_dir)
    for name in orphan_dirs(resolved, _live_worktree_paths(tasks_root), live_ids):
        st.log.info("worktree.sweep.removed", task_id=name)
        _remove_orphan_dir(worktrees_dir / name)


def _resolved_worktree_dirs(worktrees_dir: Path) -> list[tuple[str, str]]:
    """(name, resolved_path) pairs for every dir in the worktrees root."""
    pairs: list[tuple[str, str]] = []
    try:
        entries = list(worktrees_dir.iterdir())
    except OSError:
        return pairs
    for entry in entries:
        if not entry.is_dir():
            continue
        try:
            pairs.append((entry.name, str(entry.resolve())))
        except OSError:
            continue
    return pairs


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


def _read_lease_facts(st: SupervisorState, task: Task) -> _LeaseFacts:
    """Read one lease's facts from disk and the process table (I/O)."""
    task_dir = st.task_dir_for(task.id)
    attempt = latest_attempt_dir(task_dir)
    if attempt is None:
        return _LeaseFacts(_LeaseGap.NO_ATTEMPT_DIR, False, False, False, False, "", 0)
    run = RunRecord.load(attempt)
    if run is None:
        return _LeaseFacts(_LeaseGap.NO_RUN, False, False, False, False, "", 0)
    lease_until = parse_iso(run.lease_until)
    if lease_until is None:
        return _LeaseFacts(_LeaseGap.NO_HEARTBEAT, False, False, False, False, "", 0)
    pid = run.pid
    if not isinstance(pid, int) or isinstance(pid, bool):
        return _LeaseFacts(_LeaseGap.NO_PID, True, False, False, False, lease_until.isoformat(), 0)
    host = run.host
    dead = True if (isinstance(host, str) and host and host != host_name()) else not pid_alive(pid)
    history = load_attempts(task_dir)
    ended = bool(history) and history[-1].get("ended_at") is not None
    return _LeaseFacts(
        _LeaseGap.NONE,
        lease_is_stale(lease_until, st.clock.now()),
        True,
        dead,
        ended,
        lease_until.isoformat(),
        pid,
    )


def _reconcile_one_lease(st: SupervisorState, task: Task, seen: set[str]) -> None:
    """Reclaim *task* iff its lease is stale on a provably dead attempt."""
    facts = _read_lease_facts(st, task)
    verdict = classify_lease(
        has_attempt_dir=facts.gap is not _LeaseGap.NO_ATTEMPT_DIR,
        has_run=facts.gap in (_LeaseGap.NONE, _LeaseGap.NO_PID),
        lease_stale=facts.stale,
        pid_valid=facts.pid_valid,
        pid_dead=facts.pid_dead,
        attempt_ended=facts.attempt_ended,
    )
    _act_on_lease(st, task, seen, verdict, facts)


def _act_on_lease(
    st: SupervisorState, task: Task, seen: set[str], verdict: LeaseVerdict, facts: _LeaseFacts
) -> None:
    """Log or reclaim one classified lease (the act half of reconcile)."""
    if verdict is LeaseVerdict.LIVE:
        return
    if verdict is LeaseVerdict.STALE_PID_ALIVE:
        st.log.warning(
            "lease_stale_pid_alive",
            task_id=task.id,
            pid=facts.pid,
            lease_until=facts.lease_until_iso,
        )
        return
    if verdict is LeaseVerdict.RECLAIM:
        _reclaim_lease(st, task)
        return
    if facts.gap is _LeaseGap.NO_PID:
        st.log.warning("lease_no_pid", task_id=task.id)
    else:
        _log_lease_once(seen, st, facts.gap.value, task.id)


def _reclaim_lease(st: SupervisorState, task: Task) -> None:
    """Journal a lease-expired end and release the bead for re-queueing."""
    task_dir = st.task_dir_for(task.id)
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
        st.log.warning("lease_expired_released", task_id=task.id)
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
