"""Retention garbage collection: archive tasks, purge archives, drop worktrees."""

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING

from fleet.core.limits import GC_INTERVAL_SEC
from fleet.orchestrator.service import PeriodicService, ServiceOrder
from fleet.state.archive import find_stale_worktrees, gc_tasks, purge_archive

from . import worktree as worktree_mod

if TYPE_CHECKING:
    from fleet.orchestrator.state import SupervisorState


class RetentionGc(PeriodicService):
    """Run the retention pass on start and then on a daily cadence."""

    order = ServiceOrder.Gc
    name = "retention_gc"

    def __init__(self, interval_sec: float = GC_INTERVAL_SEC) -> None:
        super().__init__(interval_sec)

    async def on_start(self, st: SupervisorState) -> None:
        """Run one retention pass at startup."""
        self.run_pass(st)

    async def tick(self, st: SupervisorState) -> None:
        """Run one retention pass."""
        self.run_pass(st)

    def run_pass(self, st: SupervisorState) -> None:
        """Archive old closed tasks, purge old archives, drop stale worktrees.

        Retention windows come from the live config; 0 disables that step.
        Never raises: per-step handling is guarded so one bad directory
        cannot break the pass.
        """
        home = st.project_root
        log = st.log
        try:
            stale = find_stale_worktrees(home, days=st.config.gc_retention_days)
        except Exception as exc:  # noqa: BLE001 - selection failed, skip step
            log.warning("retention_worktrees_failed", error=str(exc))
            stale = []
        try:
            gc = gc_tasks(home, days=st.config.gc_retention_days)
            log.info(
                "retention_gc_tasks",
                archived=len(gc.archived),
                skipped=gc.skipped,
                bytes_moved=gc.bytes_moved,
            )
        except Exception as exc:  # noqa: BLE001 - one bad step, rest continue
            log.warning("retention_gc_tasks_failed", error=str(exc))
        try:
            purged = purge_archive(home, days=st.config.gc_archive_days)
            log.info(
                "retention_purge_archive",
                deleted=len(purged.deleted),
                skipped=purged.skipped,
                bytes_freed=purged.bytes_freed,
            )
        except Exception as exc:  # noqa: BLE001 - one bad step, rest continue
            log.warning("retention_purge_failed", error=str(exc))
        removed = 0
        for item in stale:
            try:
                worktree_mod.cleanup_worktree(
                    item.repo_root or home,
                    item.task_id,
                    worktree_path_arg=item.path,
                    fleet_home=home,
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
