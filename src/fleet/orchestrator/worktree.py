"""Git worktree create/merge/validate for isolated task runs.

Isolation is git-aware: a task whose cwd is inside a git repo runs in a
worktree at ``$FLEET_HOME/worktrees/<repo>-<task_id>`` on branch
``fleet/<task_id>``, forked from the repo's default branch. Tasks whose cwd
is not in a repo run in place (no worktree, no merge step).
"""

from __future__ import annotations

import os
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path


def _fleet_home(fleet_home: Path | None = None) -> Path:
    """Resolve the fleet home for worktree placement."""
    if fleet_home is not None:
        return Path(fleet_home)
    env = os.environ.get("FLEET_HOME")
    if env:
        return Path(env).expanduser().resolve()
    return Path.home() / ".fleet"


def worktrees_root(fleet_home: Path | None = None) -> Path:
    """The directory holding all isolated worktrees."""
    return _fleet_home(fleet_home) / "worktrees"


def worktree_path(
    task_id: str,
    fleet_home: Path | None = None,
    repo_name: str | None = None,
) -> Path:
    """Return the worktree dir for *task_id*.

    New dirs are ``<repo-name>-<task_id>`` (avoids collisions across repos);
    *repo_name* omitted keeps the legacy ``<task_id>`` layout (used by the
    startup sweep to find old dirs).
    """
    name = f"{repo_name}-{task_id}" if repo_name else task_id
    return worktrees_root(fleet_home) / name


def detect_repo_root(cwd: Path | str) -> Path | None:
    """Return the git toplevel containing *cwd*, or None when not a git task."""
    try:
        result = subprocess.run(
            ["git", "-C", str(cwd), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    toplevel = result.stdout.strip()
    return Path(toplevel) if toplevel else None


def resolve_base_ref(repo_root: Path | str) -> str:
    """Return the repo's default branch for merging back into.

    Prefers the remote's default (``refs/remotes/origin/HEAD``), falls back
    to the current branch, then to ``main``.
    """
    repo = str(repo_root)
    try:
        result = subprocess.run(
            ["git", "-C", repo, "symbolic-ref", "refs/remotes/origin/HEAD"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            ref = result.stdout.strip()
            # e.g. refs/remotes/origin/main -> main
            if ref.startswith("refs/remotes/origin/"):
                branch = ref[len("refs/remotes/origin/") :]
                if branch:
                    return branch
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        result = subprocess.run(
            ["git", "-C", repo, "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            branch = result.stdout.strip()
            if branch and branch != "HEAD":
                return branch
    except (OSError, subprocess.SubprocessError):
        pass
    return "main"


def _branch_exists(repo_root: Path | str, branch: str) -> bool:
    result = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "--verify", branch],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def create_worktree(
    repo_root: Path | str,
    task_id: str,
    base_ref: str = "main",
    fleet_home: Path | None = None,
) -> Path:
    """Create (or reuse) the isolated worktree for *task_id*.

    Reuses the same worktree across attempts: an existing dir is returned
    as-is, and an existing ``fleet/<task_id>`` branch is checked out instead
    of re-created.
    """
    repo = Path(repo_root)
    path = worktree_path(task_id, fleet_home=fleet_home, repo_name=repo.name)
    if path.exists():
        return path
    branch = f"fleet/{task_id}"
    if _branch_exists(repo, f"refs/heads/{branch}"):
        cmd = ["git", "-C", str(repo), "worktree", "add", str(path), branch]
    else:
        cmd = [
            "git",
            "-C",
            str(repo),
            "worktree",
            "add",
            str(path),
            "-b",
            branch,
            base_ref,
        ]
    subprocess.run(cmd, capture_output=True, text=True, check=True)
    return path


def remove_worktree(
    repo_root: Path | str,
    task_id: str,
    worktree_path_arg: Path | str | None = None,
    fleet_home: Path | None = None,
) -> None:
    """Remove the worktree for *task_id*; safe when already gone."""
    if worktree_path_arg is not None:
        path = Path(worktree_path_arg)
    else:
        repo = Path(repo_root)
        candidate = worktree_path(
            task_id, fleet_home=fleet_home, repo_name=repo.name
        )
        if candidate.exists():
            path = candidate
        else:
            # Legacy layout (<task_id> without repo prefix).
            path = worktree_path(task_id, fleet_home=fleet_home)
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


def delete_branch(repo_root: Path | str, task_id: str) -> None:
    """Delete ``fleet/<task_id>`` after a successful merge; best effort."""
    branch = f"fleet/{task_id}"
    subprocess.run(
        ["git", "-C", str(repo_root), "branch", "-D", branch],
        capture_output=True,
        text=True,
    )


def is_repo_dirty(repo_root: Path | str) -> bool:
    """True when *repo_root* has uncommitted changes (tracked files)."""
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "status", "--porcelain", "--untracked-files=no"],
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.SubprocessError):
        return True
    if result.returncode != 0:
        return True
    return bool(result.stdout.strip())


def has_uncommitted_changes(worktree_path_arg: Path | str) -> bool:
    """True when the worktree holds staged, unstaged or untracked changes.

    Anything unknown (not a git checkout, git failed) counts as dirty so a
    worker's uncommitted work is never treated as "nothing to keep".
    """
    try:
        status_result = subprocess.run(
            ["git", "-C", str(worktree_path_arg), "status", "--porcelain"],
            capture_output=True,
            text=True,
        )
    except Exception:
        return True
    if status_result.returncode != 0:
        return True
    return bool(status_result.stdout.strip())


def is_committed_clean(worktree_path_arg: Path | str, base_ref: str = "main") -> bool:
    """True when the worktree is clean AND its HEAD advanced past *base_ref*."""
    wt = str(worktree_path_arg)
    try:
        status_result = subprocess.run(
            ["git", "-C", wt, "status", "--porcelain"],
            capture_output=True,
            text=True,
        )
        if status_result.returncode != 0:
            return False
        if status_result.stdout.strip():
            return False

        head_result = subprocess.run(
            ["git", "-C", wt, "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
        )
        base_result = subprocess.run(
            ["git", "-C", wt, "rev-parse", base_ref],
            capture_output=True,
            text=True,
        )
        if head_result.returncode != 0 or base_result.returncode != 0:
            return False
        if head_result.stdout.strip() == base_result.stdout.strip():
            return False
        # Ahead of base (not just diverged sideways)?
        count = subprocess.run(
            ["git", "-C", wt, "rev-list", "--count", f"{base_ref}..HEAD"],
            capture_output=True,
            text=True,
        )
        if count.returncode != 0:
            return False
        return int(count.stdout.strip() or "0") > 0
    except Exception:
        return False


@dataclass
class MergeResult:
    ok: bool
    conflict: bool
    message: str


def merge_to_base(
    repo_root: Path | str,
    task_id: str,
    base_ref: str = "main",
) -> MergeResult:
    """Merge ``fleet/<task_id>`` into *base_ref* inside *repo_root*.

    Never checks out inside a dirty base: callers must treat a dirty base as
    "merge manually" without touching the repo. This function double-checks
    and refuses as well.
    """
    repo = str(repo_root)
    branch = f"fleet/{task_id}"

    if is_repo_dirty(repo):
        return MergeResult(
            ok=False, conflict=False, message="base repo dirty; merge manually"
        )

    checkout_result = subprocess.run(
        ["git", "-C", repo, "checkout", base_ref],
        capture_output=True,
        text=True,
    )
    if checkout_result.returncode != 0:
        return MergeResult(ok=False, conflict=False, message=checkout_result.stderr)

    # Prefer a fast-forward when possible; otherwise a --no-ff merge commit.
    ff_result = subprocess.run(
        ["git", "-C", repo, "merge", "--ff-only", branch],
        capture_output=True,
        text=True,
    )
    if ff_result.returncode == 0:
        return MergeResult(ok=True, conflict=False, message="merged")

    merge_result = subprocess.run(
        ["git", "-C", repo, "merge", "--no-ff", branch, "-m", f"merge {branch}"],
        capture_output=True,
        text=True,
    )

    if merge_result.returncode == 0:
        return MergeResult(ok=True, conflict=False, message="merged")

    combined_output = merge_result.stdout + merge_result.stderr
    is_conflict = "CONFLICT" in combined_output
    if not is_conflict:
        ls_result = subprocess.run(
            ["git", "-C", repo, "ls-files", "-u"],
            capture_output=True,
            text=True,
        )
        if ls_result.returncode == 0 and ls_result.stdout.strip():
            is_conflict = True

    if is_conflict:
        subprocess.run(
            ["git", "-C", repo, "merge", "--abort"],
            capture_output=True,
            text=True,
        )
        return MergeResult(ok=False, conflict=True, message=merge_result.stderr)

    return MergeResult(ok=False, conflict=False, message=merge_result.stderr)


POST_MERGE_TIMEOUT_SEC = 600


def run_post_merge_command(
    command: str,
    cwd: Path | str,
    timeout_sec: int = POST_MERGE_TIMEOUT_SEC,
) -> tuple[bool, str]:
    """Run the configured post-merge command; return (ok, last-40-lines).

    Empty command means "no validation step": returns (True, "").
    """
    if not command.strip():
        return True, ""
    try:
        argv = shlex.split(command)
    except ValueError as exc:
        return False, f"bad post_merge_command: {exc}"
    try:
        result = subprocess.run(
            argv,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout_sec,
        )
    except subprocess.TimeoutExpired as exc:
        out = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
        err = (exc.stderr or "") if isinstance(exc.stderr, str) else ""
        tail = "\n".join((out + "\n" + err).splitlines()[-40:])
        return False, tail or f"post_merge_command timed out after {timeout_sec}s"
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    combined = (result.stdout or "") + ("\n" if result.stdout else "") + (result.stderr or "")
    tail = "\n".join(combined.splitlines()[-40:])
    return result.returncode == 0, tail


def ensure_worktree(
    repo_root: Path | str,
    task_id: str,
    base_ref: str = "main",
    fleet_home: Path | None = None,
) -> Path:
    """Ensure a worktree exists for *task_id* (no env gate; caller decides)."""
    return create_worktree(repo_root, task_id, base_ref, fleet_home=fleet_home)


def cleanup_worktree(
    repo_root: Path | str,
    task_id: str,
    worktree_path_arg: Path | str | None = None,
    fleet_home: Path | None = None,
) -> None:
    """Remove the worktree for *task_id* if it exists.

    Swallows errors when the worktree is already gone so the call is safe
    at task shutdown regardless of prior state.
    """
    try:
        remove_worktree(repo_root, task_id, worktree_path_arg, fleet_home=fleet_home)
    except Exception:
        pass


def is_task_advanced(worktree_path_arg: Path | str, base_ref: str = "main") -> bool:
    """Return ``True`` when the worktree has advanced past *base_ref*.

    This is a convenience wrapper around :func:`is_committed_clean` — it
    tells you whether the worktree did any commits since ``base_ref``.
    """
    return is_committed_clean(worktree_path_arg, base_ref)
