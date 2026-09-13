"""Retention garbage collection: archive tasks, purge archives, drop worktrees.

Called by ``orchestrator/`` ``default_services`` (wiring). The work is one
``retention_gc_pass`` function run both at startup and on the daily
cadence; ``make_retention_gc`` wraps it in a ``PeriodicService``.
"""

from __future__ import annotations

import re
import shutil
import time
from typing import TYPE_CHECKING

from fleet.beads.client import BdClient, BdError
from fleet.beads.status_cache import get_beads_status_map
from fleet.core.limits import GC_INTERVAL_SEC
from fleet.orchestrator.service import PeriodicService, ServiceOrder
from fleet.state.archive import apply_gc, apply_purge, find_stale_worktrees, plan_gc, plan_purge

from . import worktree as worktree_mod

if TYPE_CHECKING:
    from fleet.orchestrator.state import SupervisorState


async def retention_gc_on_start(st: SupervisorState) -> None:
    """Run one retention pass at startup."""
    retention_gc_pass(st)


async def retention_gc_tick(st: SupervisorState) -> None:
    """Run one retention pass."""
    retention_gc_pass(st)


def retention_gc_pass(st: SupervisorState) -> None:
    """Archive old closed tasks, purge old archives, drop stale worktrees.

    Retention windows come from the live config; 0 disables that step.
    Never raises: per-step handling is guarded so one bad directory
    cannot break the pass.
    """
    fleet_home = st.fleet_home
    log = st.log
    beads_map = get_beads_status_map(fleet_home)
    try:
        stale = find_stale_worktrees(fleet_home, days=st.config.gc_retention_days)
    except Exception as exc:  # noqa: BLE001 - selection failed, skip step
        log.warning("retention_worktrees_failed", error=str(exc))
        stale = []
    try:
        gc = apply_gc(
            fleet_home, plan_gc(fleet_home, days=st.config.gc_retention_days, beads_map=beads_map)
        )
        log.info(
            "retention_gc_tasks",
            archived=len(gc.archived),
            skipped=gc.skipped,
            bytes_moved=gc.bytes_moved,
            closed_from_beads=gc.closed_from_beads,
        )
    except Exception as exc:  # noqa: BLE001 - one bad step, rest continue
        log.warning("retention_gc_tasks_failed", error=str(exc))
    try:
        purged = apply_purge(fleet_home, plan_purge(fleet_home, days=st.config.gc_archive_days))
        log.info(
            "retention_purge_archive",
            deleted=len(purged.deleted),
            skipped=purged.skipped,
            bytes_freed=purged.bytes_freed,
        )
    except Exception as exc:  # noqa: BLE001 - one bad step, rest continue
        log.warning("retention_purge_failed", error=str(exc))
    _run_bd_gc(st, beads_map)
    removed = 0
    for item in stale:
        try:
            worktree_mod.cleanup_worktree(
                item.repo_root or fleet_home,
                item.task_id,
                worktree_path_arg=item.path,
                fleet_home=fleet_home,
            )
            if item.path.exists():
                # Not a git-registered worktree (or its repo is gone):
                # fall back to a plain recursive delete.
                shutil.rmtree(item.path, ignore_errors=True)
            removed += 1
        except Exception as exc:  # noqa: BLE001 - one bad dir, rest continue
            log.warning(
                "retention_worktree_failed",
                task_id=item.task_id,
                error=str(exc),
            )
    if stale:
        log.info("retention_worktrees", found=len(stale), removed=removed)


def _run_bd_gc(st: SupervisorState, beads_map: dict[str, dict] | None) -> None:
    """Decay and compact the beads database itself, guarded by config and state.

    Skipped when disabled, when the retention window is 0, or while any bead
    is in progress (a `bd gc` mid-run could race a worker's own bd calls).
    Never raises: a BdError is logged and the pass continues.
    """
    days = st.config.gc_retention_days
    if not st.config.gc_beads or days <= 0:
        return
    if beads_map and any(item.get("status") == "in_progress" for item in beads_map.values()):
        return
    client = BdClient(st.fleet_home)
    started = time.monotonic()
    try:
        result = client.run(["gc", "--older-than", str(days), "--force"])
        deleted = _count_from_gc_output(result.stdout)
        client.run(["compact", "--days", str(days)])
        st.log.info(
            "retention_bd_gc",
            deleted=deleted,
            duration_sec=round(time.monotonic() - started, 3),
        )
    except BdError as exc:
        st.log.warning("retention_bd_gc_failed", error=str(exc))


_GC_DECAY_RE = re.compile(r"Decay:\s*(\d+)\s*issues?\s*deleted", re.IGNORECASE)


def _count_from_gc_output(stdout: str) -> int | None:
    """Best-effort count of deleted beads parsed from `bd gc`'s "Decay: N issues deleted" line."""
    match = _GC_DECAY_RE.search(stdout)
    return int(match.group(1)) if match else None


def make_retention_gc(interval_sec: float = GC_INTERVAL_SEC) -> PeriodicService:
    """Build the retention-gc periodic service (startup pass + daily cadence)."""
    return PeriodicService(
        name="retention_gc",
        order=ServiceOrder.Gc,
        interval_sec=interval_sec,
        tick=retention_gc_tick,
        on_start=retention_gc_on_start,
    )
