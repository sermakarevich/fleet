"""Merge or drop a flow coder step's isolated worktree (Fleet 2 cutover C2).

A coder step with ``isolation: worktree`` works on branch ``fleet/<task id>``
in a worktree (see ``orchestrator/spawn._ensure_isolation``; the step's task
id is ``<run id>.<step>`` or ``<run id>.<step>.<index>`` per
``orchestrator/flow_coder.step_task_id``). Nothing merges that branch back:
the bead flow (and any flow that wants its coder's commits) adds a tool step
running ``fleet worktree merge`` for exactly that.

Sync, no ``SupervisorState``: follows ``merge_validation._validate_locked`` +
``_merge`` step by step, returning a :class:`MergeOutcome` instead of
blocking a bead. Called by ``cli/worktree.py``.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from pathlib import Path

from fleet.beads.task_store import TaskStore
from fleet.core import isolation
from fleet.core.config import RuntimeConfig
from fleet.orchestrator import worktree
from fleet.state import paths


@dataclass(frozen=True)
class MergeOutcome:
    """What happened to one isolated step worktree: merge, drop, or refusal."""

    ok: bool
    task_id: str
    repo_root: str = ""
    base_ref: str = ""
    branch: str = ""
    merged: bool = False
    conflict_files: tuple[str, ...] = ()
    message: str = ""


def _clear_isolation_info(fleet_home: Path, task_id: str) -> None:
    """Drop repo_root/base_ref/worktree_path from task.json; never raises."""
    with contextlib.suppress(Exception):
        TaskStore(fleet_home).clear_isolation_info(task_id)


def _cleanup(repo_root: Path, task_id: str, wt_path: Path, fleet_home: Path) -> None:
    """Remove the worktree; never raises (keeps the branch)."""
    with contextlib.suppress(Exception):
        worktree.cleanup_worktree(repo_root, task_id, wt_path, fleet_home=fleet_home)


def _delete_branch(repo_root: Path, task_id: str) -> None:
    """Delete ``fleet/<task id>``; never raises (best effort)."""
    with contextlib.suppress(Exception):
        worktree.delete_branch(repo_root, task_id)


def _refuse(
    task_id: str,
    repo_root: Path,
    base_ref: str,
    message: str,
    conflict_files: tuple[str, ...] = (),
) -> MergeOutcome:
    """An ``ok=False`` outcome carrying the resolved repo fields and *message*."""
    return MergeOutcome(
        ok=False,
        task_id=task_id,
        repo_root=str(repo_root),
        base_ref=base_ref,
        branch=f"fleet/{task_id}",
        conflict_files=conflict_files,
        message=message,
    )


def _check_ready(
    fleet_home: Path, task_id: str, repo_root: Path, base_ref: str, wt_path: Path
) -> MergeOutcome | None:
    """Refusal outcome for steps 2-4, or None when the branch is ready to merge.

    A gone repo or a dirty base keeps everything; a missing or not-ahead
    worktree is removed but the branch is kept.
    """
    if not repo_root.is_dir():
        return _refuse(
            task_id, repo_root, base_ref, f"repo_root gone ({repo_root}); merge manually"
        )
    if worktree.is_repo_dirty(repo_root):
        return _refuse(task_id, repo_root, base_ref, "base repo dirty; merge manually")
    if not wt_path.is_dir() or not worktree.is_committed_clean(wt_path, base_ref=base_ref):
        _cleanup(repo_root, task_id, wt_path, fleet_home)
        return _refuse(
            task_id, repo_root, base_ref, f"worktree not clean/ahead of {base_ref}; merge manually"
        )
    return None


def _merge_branch(
    fleet_home: Path,
    config: RuntimeConfig,
    task_id: str,
    repo_root: Path,
    base_ref: str,
    wt_path: Path,
) -> MergeOutcome | None:
    """Refusal outcome for steps 5-6, or None when merge and gate succeeded.

    A failed merge or gate removes the worktree but keeps the branch.
    """
    branch = f"fleet/{task_id}"
    result = worktree.merge_to_base(repo_root, task_id, base_ref=base_ref)
    if not result.ok:
        _cleanup(repo_root, task_id, wt_path, fleet_home)
        if result.conflict:
            return _refuse(
                task_id,
                repo_root,
                base_ref,
                f"merge conflict into {base_ref}; branch {branch} kept",
                conflict_files=result.conflict_files,
            )
        return _refuse(task_id, repo_root, base_ref, result.message)
    post_cmd = getattr(config, "post_merge_command", "") or ""
    if post_cmd.strip():
        ok, tail = worktree.run_post_merge_command(post_cmd, repo_root)
        if not ok:
            _cleanup(repo_root, task_id, wt_path, fleet_home)
            return _refuse(task_id, repo_root, base_ref, f"post-merge command failed:\n{tail}")
    return None


def merge_task_worktree(
    fleet_home: Path,
    config: RuntimeConfig,
    task_id: str,
    *,
    keep_branch: bool = False,
) -> MergeOutcome:
    """Merge a finished coder step's worktree branch into its base ref.

    Mirrors ``merge_validation._validate_locked`` + ``_merge``: dirty base
    keeps everything; a missing or not-ahead worktree is removed but the
    branch kept; a conflict removes the worktree but keeps the branch; only
    success (plus ``keep_branch=False``) deletes the branch. Clears the
    isolation info in task.json on success so a second merge reports
    ``no isolation info``. Never raises for missing dirs.
    """
    branch = f"fleet/{task_id}"
    info = isolation.read(paths.task_dir(fleet_home, task_id))
    if info is None:
        return MergeOutcome(ok=False, task_id=task_id, message=f"no isolation info for {task_id}")
    repo_root = Path(info.repo_root)
    base_ref = info.base_ref or "main"
    wt_path = Path(info.worktree_path)
    ready = _check_ready(fleet_home, task_id, repo_root, base_ref, wt_path)
    if ready is not None:
        return ready
    refused = _merge_branch(fleet_home, config, task_id, repo_root, base_ref, wt_path)
    if refused is not None:
        return refused
    _cleanup(repo_root, task_id, wt_path, fleet_home)
    if not keep_branch:
        _delete_branch(repo_root, task_id)
    _clear_isolation_info(fleet_home, task_id)
    return MergeOutcome(
        ok=True,
        task_id=task_id,
        repo_root=str(repo_root),
        base_ref=base_ref,
        branch=branch,
        merged=True,
        message=f"merged {branch} into {base_ref}",
    )


def drop_task_worktree(fleet_home: Path, task_id: str) -> MergeOutcome:
    """Remove a coder step's worktree and branch without merging.

    Used on the failure path: whatever the step left behind goes away and
    the isolation info is cleared. ``ok=True`` always, including the
    not-isolated no-op. Never raises for missing dirs.
    """
    branch = f"fleet/{task_id}"
    info = isolation.read(paths.task_dir(fleet_home, task_id))
    if info is None:
        return MergeOutcome(ok=True, task_id=task_id, branch=branch, message="not isolated")
    repo_root = Path(info.repo_root)
    base_ref = info.base_ref or "main"
    if info.repo_root and repo_root.is_dir():
        _cleanup(repo_root, task_id, Path(info.worktree_path), fleet_home)
        _delete_branch(repo_root, task_id)
    _clear_isolation_info(fleet_home, task_id)
    return MergeOutcome(
        ok=True,
        task_id=task_id,
        repo_root=info.repo_root,
        base_ref=base_ref,
        branch=branch,
        message=f"dropped {branch}",
    )
