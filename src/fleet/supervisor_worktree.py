"""Supervisor bridge to the dormant worktree module.

This module imports ONLY from ``fleet.worktree``. It is a thin bridge that
may be wired into the supervisor / runner in a future task. It changes zero
runtime behavior on its own — it is called by no existing code.
"""

from __future__ import annotations

from pathlib import Path

from fleet.worktree import (
    create_worktree,
    is_committed_clean,
    remove_worktree,
    worktree_isolation_enabled,
    worktree_path,
)

__all__ = [
    "create_worktree",
    "is_committed_clean",
    "remove_worktree",
    "worktree_isolation_enabled",
    "worktree_path",
    "ensure_worktree",
    "cleanup_worktree",
    "is_task_advanced",
]


def ensure_worktree(
    repo_root: Path, task_id: str, base_ref: str = "main"
) -> Path | None:
    """Ensure a worktree exists for *task_id*.

    Returns the worktree directory on disk, or ``None`` when worktree
    isolation is disabled (dormant).
    """
    if not worktree_isolation_enabled():
        return None

    return create_worktree(repo_root, task_id, base_ref)


def cleanup_worktree(repo_root: Path, task_id: str) -> None:
    """Remove the worktree for *task_id* if it exists.

    Swallows errors when the worktree is already gone so the call is safe
    at task shutdown regardless of prior state.
    """
    try:
        remove_worktree(repo_root, task_id)
    except Exception:
        pass


def is_task_advanced(worktree_path_arg: Path, base_ref: str = "main") -> bool:
    """Return ``True`` when the worktree has advanced past *base_ref*.

    This is a convenience wrapper around :func:`fleet.worktree.is_committed_clean`
    — it tells you whether the worktree did any commits since ``base_ref``.
    """
    return is_committed_clean(worktree_path_arg, base_ref)
