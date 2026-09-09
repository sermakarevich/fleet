"""Merge validation service: merge validated worktrees into their base ref.

Runs on the claim cadence. Each tick merges at most one task dir carrying
a `.needs_validation` marker; tasks still present in `st.running` are
skipped. Failures block the bead with a reason instead of closing it.
"""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path
from typing import TYPE_CHECKING

from fleet.core.isolation import read as read_isolation_info
from fleet.core.limits import CLAIM_POLL_INTERVAL_SEC
from fleet.orchestrator.service import ServiceOrder, run_periodic
from fleet.state import paths as state_paths
from fleet.state.task_meta import TaskMeta
from fleet.state.validation_marker import (
    clear_needs_validation,
    needs_validation,
    release_validation_lock,
    try_acquire_validation_lock,
)

from . import worktree

if TYPE_CHECKING:
    from fleet.orchestrator.state import SupervisorState


def finish_validation(st: SupervisorState, task_dir: Path, task_id: str) -> None:
    """Clear validation state and drop isolation info after a terminal merge."""
    clear_needs_validation(task_dir)
    (task_dir / ".worktree").unlink(missing_ok=True)
    try:
        st.queue.clear_isolation_info(task_id)
    except AttributeError:
        pass
    except Exception:
        pass


async def validate_one(st: SupervisorState, task_dir: Path, task_id: str) -> None:
    """Merge one validated worktree into its base ref, generically.

    Exclusive per task dir: the first holder of the ``.validating`` lock
    wins; losers return without touching the bead. The winner re-checks
    the marker and the bead status after acquiring, so a validation that
    already merged (marker gone, bead closed) is skipped, never re-blocked.
    """
    fd = try_acquire_validation_lock(task_dir)
    if fd is None:
        st.log.debug("task.validation_skipped_locked", task_id=task_id)
        return
    try:
        if not needs_validation(task_dir):
            return
        if await asyncio.to_thread(_is_closed, st, task_id):
            st.log.info("task.validation_skipped_closed", task_id=task_id)
            clear_needs_validation(task_dir)
            return
        await _validate_locked(st, task_dir, task_id)
    finally:
        release_validation_lock(fd, task_dir)


def _is_closed(st: SupervisorState, task_id: str) -> bool:
    """True when the bead already reads closed (missing bead counts as open)."""
    try:
        return st.queue.get(task_id).status == "closed"
    except Exception as exc:
        st.log.debug("task.validation_status_unknown", task_id=task_id, error=str(exc))
        return False


async def _block_unless_closed(st: SupervisorState, task_id: str, reason: str) -> None:
    """Block the bead unless it already closed (a won merge must never regress)."""
    if await asyncio.to_thread(_is_closed, st, task_id):
        st.log.info("task.validation_skipped_closed", task_id=task_id)
        return
    await asyncio.to_thread(st.queue.set_blocked, task_id, reason)


async def _validate_locked(st: SupervisorState, task_dir: Path, task_id: str) -> None:
    """Merge one validated worktree; caller holds the task's validation lock."""
    info = read_isolation_info(task_dir)
    if info is None or not info.repo_root:
        await _block_unless_closed(
            st,
            task_id,
            "validation failed: missing isolation info; merge manually",
        )
        st.log.warning("task.validation_no_info", task_id=task_id)
        clear_needs_validation(task_dir)
        return
    repo_root = Path(info.repo_root)
    base_ref = info.base_ref or "main"
    wt_path = Path(info.worktree_path)

    if not repo_root.is_dir():
        await _block_unless_closed(
            st,
            task_id,
            f"validation failed: repo_root gone ({repo_root}); merge manually",
        )
        clear_needs_validation(task_dir)
        return

    if worktree.is_repo_dirty(repo_root):
        await _block_unless_closed(st, task_id, "base repo dirty; merge manually")
        st.log.warning("task.validation_dirty_base", task_id=task_id)
        clear_needs_validation(task_dir)
        return

    if not wt_path.is_dir() or not worktree.is_committed_clean(wt_path, base_ref=base_ref):
        await _not_clean(st, task_dir, task_id, repo_root, wt_path, base_ref)
        return

    await _merge(st, task_dir, task_id, repo_root, wt_path, base_ref)


async def _not_clean(
    st: SupervisorState,
    task_dir: Path,
    task_id: str,
    repo_root: Path,
    wt_path: Path,
    base_ref: str,
) -> None:
    """Block a worktree that is gone or not ahead, unless the bead closed."""
    await _block_unless_closed(
        st,
        task_id,
        f"validation failed: worktree not clean/ahead of {base_ref}; merge manually",
    )
    st.log.warning("task.validation_not_clean", task_id=task_id)
    worktree.cleanup_worktree(repo_root, task_id, wt_path, fleet_home=st.fleet_home)
    finish_validation(st, task_dir, task_id)


async def _merge(
    st: SupervisorState,
    task_dir: Path,
    task_id: str,
    repo_root: Path,
    wt_path: Path,
    base_ref: str,
) -> None:
    """Merge the branch, run the post-merge gate, then close the bead."""
    result = worktree.merge_to_base(repo_root, task_id, base_ref=base_ref)
    if not result.ok:
        reason = (
            f"merge conflict into {base_ref}; resolve on branch fleet/{task_id} then close"
            if result.conflict
            else f"validation merge failed: {result.message}"
        )
        await _block_unless_closed(st, task_id, reason)
        st.log.warning("task.validation_failed", task_id=task_id, conflict=result.conflict)
        worktree.cleanup_worktree(repo_root, task_id, wt_path, fleet_home=st.fleet_home)
        if result.conflict:
            # The branch is kept (delete_branch runs only on success); record
            # where it lives before finish_validation drops the isolation info.
            try:
                TaskMeta.update(
                    task_dir,
                    merge_conflict={
                        "repo_root": str(repo_root),
                        "base_ref": base_ref,
                        "branch": f"fleet/{task_id}",
                        "files": list(result.conflict_files),
                    },
                )
            except OSError as exc:
                st.log.warning("task.conflict_record_failed", task_id=task_id, error=str(exc))
        finish_validation(st, task_dir, task_id)
        return

    post_cmd = getattr(st.config, "post_merge_command", "") or ""
    if post_cmd.strip():
        ok, tail = await asyncio.to_thread(worktree.run_post_merge_command, post_cmd, repo_root)
        if not ok:
            await _block_unless_closed(st, task_id, f"post-merge command failed:\n{tail}")
            st.log.warning("task.post_merge_failed", task_id=task_id)
            worktree.cleanup_worktree(repo_root, task_id, wt_path, fleet_home=st.fleet_home)
            finish_validation(st, task_dir, task_id)
            return

    await asyncio.to_thread(
        st.queue.close, task_id, reason=f"validated: merged fleet/{task_id} into {base_ref}"
    )
    st.log.info("task.validated", task_id=task_id)
    worktree.cleanup_worktree(repo_root, task_id, wt_path, fleet_home=st.fleet_home)
    with contextlib.suppress(Exception):
        await asyncio.to_thread(worktree.delete_branch, repo_root, task_id)
    finish_validation(st, task_dir, task_id)


async def run_pending_validations(st: SupervisorState) -> None:
    """Merge the first validated task dir found; at most one per tick."""
    tasks_root = state_paths.tasks_root(st.fleet_home)
    if not tasks_root.exists():
        return
    for task_dir in sorted(tasks_root.iterdir()):
        task_id = task_dir.name
        if task_id in st.running:
            continue
        if not needs_validation(task_dir):
            continue
        await validate_one(st, task_dir, task_id)
        return  # ONE per tick


class MergeValidation:
    """Validate and merge finished isolated work on the claim cadence."""

    order = ServiceOrder.Claim
    name = "merge_validation"

    def __init__(self, interval_sec: float | None = None) -> None:
        self.interval_sec = interval_sec if interval_sec is not None else CLAIM_POLL_INTERVAL_SEC

    async def tick(self, st: SupervisorState) -> None:
        """Merge one pending validation, if any."""
        await run_pending_validations(st)

    async def serve(self, st: SupervisorState) -> None:
        """Tick on the claim cadence until shutdown (shared periodic loop)."""
        await run_periodic(self.name, self.interval_sec, self.tick, st)
