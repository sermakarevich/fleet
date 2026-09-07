"""Git worktree create/merge/validate for isolated task runs. Env-gated off by default."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
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


@dataclass
class MergeResult:
    ok: bool
    conflict: bool
    message: str


def merge_to_base(repo_root: Path, task_id: str, base_ref: str = "main") -> MergeResult:
    branch = f"fleet/{task_id}"

    # 1. checkout base
    checkout_result = subprocess.run(
        ["git", "-C", str(repo_root), "checkout", base_ref],
        capture_output=True,
        text=True,
    )
    if checkout_result.returncode != 0:
        return MergeResult(ok=False, conflict=False, message=checkout_result.stderr)

    # 2. attempt merge (no check=True — we inspect return code)
    merge_result = subprocess.run(
        [
            "git",
            "-C",
            str(repo_root),
            "merge",
            "--no-ff",
            branch,
            "-m",
            f"merge {branch}",
        ],
        capture_output=True,
        text=True,
    )

    if merge_result.returncode == 0:
        return MergeResult(ok=True, conflict=False, message="merged")

    # Non-zero return: detect conflict via stderr/stdout "CONFLICT" or unmerged files
    combined_output = merge_result.stdout + merge_result.stderr
    is_conflict = "CONFLICT" in combined_output
    if not is_conflict:
        # Double-check with ls-files -u
        ls_result = subprocess.run(
            ["git", "-C", str(repo_root), "ls-files", "-u"],
            capture_output=True,
            text=True,
        )
        if ls_result.returncode == 0 and ls_result.stdout.strip():
            is_conflict = True

    if is_conflict:
        subprocess.run(
            ["git", "-C", str(repo_root), "merge", "--abort"],
            capture_output=True,
            text=True,
        )
        return MergeResult(ok=False, conflict=True, message=merge_result.stderr)

    return MergeResult(ok=False, conflict=False, message=merge_result.stderr)


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

    This is a convenience wrapper around :func:`is_committed_clean` — it
    tells you whether the worktree did any commits since ``base_ref``.
    """
    return is_committed_clean(worktree_path_arg, base_ref)
