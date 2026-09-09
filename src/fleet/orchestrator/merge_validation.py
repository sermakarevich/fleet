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

from fleet.core.limits import CLAIM_POLL_INTERVAL_SEC
from fleet.orchestrator.service import ServiceOrder, run_periodic
from fleet.state.paths import tasks_root as _tasks_root
from fleet.state.validation_marker import clear_needs_validation, needs_validation

from . import worktree
from .claim import read_isolation_info

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
    """Merge one validated worktree into its base ref, generically."""
    info = read_isolation_info(task_dir)
    if info is None or not info.get("repo_root"):
        await asyncio.to_thread(
            st.queue.set_blocked,
            task_id,
            "validation failed: missing isolation info; merge manually",
        )
        st.log.warning("task.validation_no_info", task_id=task_id)
        clear_needs_validation(task_dir)
        return
    repo_root = Path(info["repo_root"])
    base_ref = info.get("base_ref") or "main"
    wt_path = Path(info["worktree_path"])

    if not repo_root.is_dir():
        await asyncio.to_thread(
            st.queue.set_blocked,
            task_id,
            f"validation failed: repo_root gone ({repo_root}); merge manually",
        )
        clear_needs_validation(task_dir)
        return

    if worktree.is_repo_dirty(repo_root):
        await asyncio.to_thread(st.queue.set_blocked, task_id, "base repo dirty; merge manually")
        st.log.warning("task.validation_dirty_base", task_id=task_id)
        clear_needs_validation(task_dir)
        return

    if not wt_path.is_dir() or not worktree.is_committed_clean(wt_path, base_ref=base_ref):
        await asyncio.to_thread(
            st.queue.set_blocked,
            task_id,
            f"validation failed: worktree not clean/ahead of {base_ref}; merge manually",
        )
        st.log.warning("task.validation_not_clean", task_id=task_id)
        worktree.cleanup_worktree(repo_root, task_id, wt_path, fleet_home=st.project_root)
        finish_validation(st, task_dir, task_id)
        return

    result = worktree.merge_to_base(repo_root, task_id, base_ref=base_ref)
    if not result.ok:
        reason = (
            f"merge conflict into {base_ref}; resolve on branch fleet/{task_id} then close"
            if result.conflict
            else f"validation merge failed: {result.message}"
        )
        await asyncio.to_thread(st.queue.set_blocked, task_id, reason)
        st.log.warning("task.validation_failed", task_id=task_id, conflict=result.conflict)
        worktree.cleanup_worktree(repo_root, task_id, wt_path, fleet_home=st.project_root)
        finish_validation(st, task_dir, task_id)
        return

    post_cmd = getattr(st.config, "post_merge_command", "") or ""
    if post_cmd.strip():
        ok, tail = await asyncio.to_thread(worktree.run_post_merge_command, post_cmd, repo_root)
        if not ok:
            await asyncio.to_thread(
                st.queue.set_blocked, task_id, f"post-merge command failed:\n{tail}"
            )
            st.log.warning("task.post_merge_failed", task_id=task_id)
            worktree.cleanup_worktree(repo_root, task_id, wt_path, fleet_home=st.project_root)
            finish_validation(st, task_dir, task_id)
            return

    await asyncio.to_thread(
        st.queue.close, task_id, reason=f"validated: merged fleet/{task_id} into {base_ref}"
    )
    st.log.info("task.validated", task_id=task_id)
    worktree.cleanup_worktree(repo_root, task_id, wt_path, fleet_home=st.project_root)
    with contextlib.suppress(Exception):
        await asyncio.to_thread(worktree.delete_branch, repo_root, task_id)
    finish_validation(st, task_dir, task_id)


async def run_pending_validations(st: SupervisorState) -> None:
    """Merge the first validated task dir found; at most one per tick."""
    tasks_root = _tasks_root(st.project_root)
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
