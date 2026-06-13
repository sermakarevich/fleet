"""Pure git worktree helpers — dormant (env-gated off by default).

This module does NOT import any fleet sub-package (supervisor/runner/queue).
It changes zero runtime behavior — it is called by no existing code.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


def worktree_isolation_enabled() -> bool:
    return os.environ.get("FLEET_WORKTREE_ISOLATION", "0") == "1"


def worktree_path(task_id: str) -> Path:
    home = os.environ.get("FLEET_HOME")
    if home:
        return Path(home).expanduser().resolve() / "worktrees" / task_id
    return Path.home() / ".fleet" / "worktrees" / task_id


def create_worktree(repo_root: Path, task_id: str, base_ref: str = "main") -> Path:
    path = worktree_path(task_id)
    if path.exists():
        return path

    branch = f"fleet/{task_id}"

    subprocess.run(
        [
            "git",
            "-C",
            str(repo_root),
            "worktree",
            "add",
            str(path),
            "-b",
            branch,
            base_ref,
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    return path


def remove_worktree(repo_root: Path, task_id: str) -> None:
    path = worktree_path(task_id)
    result = subprocess.run(
        ["git", "-C", str(repo_root), "worktree", "remove", "--force", str(path)],
        capture_output=True,
        text=True,
    )
    if (
        result.returncode != 0
        and "does not exist" not in result.stderr
        and "is not a working tree" not in result.stderr
    ):
        raise RuntimeError(f"git worktree remove failed: {result.stderr}")


def is_committed_clean(worktree_path_arg: Path, base_ref: str = "main") -> bool:
    try:
        # Check clean tree
        status_result = subprocess.run(
            ["git", "-C", str(worktree_path_arg), "status", "--porcelain"],
            capture_output=True,
            text=True,
        )
        if status_result.returncode != 0:
            return False
        if status_result.stdout.strip():
            return False

        # Check HEAD vs base_ref
        head_result = subprocess.run(
            ["git", "-C", str(worktree_path_arg), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
        )
        base_result = subprocess.run(
            ["git", "-C", str(worktree_path_arg), "rev-parse", base_ref],
            capture_output=True,
            text=True,
        )
        if head_result.returncode != 0 or base_result.returncode != 0:
            return False
        return head_result.stdout.strip() != base_result.stdout.strip()
    except Exception:
        return False
