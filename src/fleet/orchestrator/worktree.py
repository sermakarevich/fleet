"""Git worktree create/merge/validate for isolated task runs.

Isolation is git-aware: a task whose cwd is inside a git repo runs in a
worktree at ``$FLEET_HOME/worktrees/<repo>-<task_id>`` on branch
``fleet/<task_id>``, forked from the repo's default branch. Tasks whose cwd
is not in a repo run in place (no worktree, no merge step).

The shape: ``TaskWorktree`` (frozen dataclass) owns every worktree
operation for one task; ``GitRepo`` (``orchestrator/git.py``) owns every
git invocation; ``core/git_status.py`` classifies git output. The
module-level functions below are thin wrappers over ``TaskWorktree`` for
the existing call sites (spawn, reap, merge_validation, leases,
retention_gc). Merging splits into pure ``plan_merge`` plus ``execute``.
"""

from __future__ import annotations

import contextlib
import shlex
import subprocess
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from fleet.core.errors import WorktreeError
from fleet.core.git_status import RepoStatus, classify_status, is_ahead, is_merge_conflict
from fleet.state.paths import fleet_home as resolve_fleet_home

from .git import GitRepo


def worktrees_root(fleet_home: Path | None = None) -> Path:
    """The directory holding all isolated worktrees."""
    return (Path(fleet_home) if fleet_home is not None else resolve_fleet_home()) / "worktrees"


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
    out = GitRepo(Path(cwd)).rev_parse("--show-toplevel")
    text = out.strip()
    return Path(text) if text else None


def resolve_base_ref(repo_root: Path | str) -> str:
    """Return the repo's default branch for merging back into.

    Prefers the remote's default (``refs/remotes/origin/HEAD``), falls back
    to the current branch, then to ``main``.
    """
    repo = GitRepo(Path(repo_root))
    ref = repo.run("symbolic-ref", "refs/remotes/origin/HEAD")
    if ref.returncode == 0:
        text = ref.stdout.strip()
        # e.g. refs/remotes/origin/main -> main
        if text.startswith("refs/remotes/origin/"):
            branch = text[len("refs/remotes/origin/") :]
            if branch:
                return branch
    current = repo.run("rev-parse", "--abbrev-ref", "HEAD")
    if current.returncode == 0:
        branch = current.stdout.strip()
        if branch and branch != "HEAD":
            return branch
    return "main"


class MergeStep(StrEnum):
    """One ordered step of a worktree merge plan."""

    CHECKOUT_BASE = "checkout_base"
    FF_ONLY = "ff_only"
    MERGE_NO_FF = "merge_no_ff"


def plan_merge(base_status: RepoStatus, branch: str, base_ref: str) -> list[MergeStep] | None:
    """Plan merging *branch* into *base_ref*; None when the base is dirty.

    Pure: a dirty base means "merge manually" without touching the repo.
    """
    _ = (branch, base_ref)
    if base_status.dirty:
        return None
    return [MergeStep.CHECKOUT_BASE, MergeStep.FF_ONLY, MergeStep.MERGE_NO_FF]


@dataclass(frozen=True, slots=True)
class MergeResult:
    """Outcome of merging a task worktree branch back to base."""

    ok: bool
    conflict: bool
    message: str


@dataclass(frozen=True, slots=True)
class TaskWorktree:
    """Every worktree operation for one task: create/remove/cleanup/merge."""

    repo: GitRepo
    task_id: str
    base_ref: str = "main"
    fleet_home: Path | None = None

    @property
    def branch(self) -> str:
        """The isolation branch for this task."""
        return f"fleet/{self.task_id}"

    @property
    def path(self) -> Path:
        """The worktree dir for this task (repo-prefixed layout)."""
        return worktree_path(
            self.task_id, fleet_home=self.fleet_home, repo_name=self.repo.root.name
        )

    def create(self) -> Path:
        """Create (or reuse) this task's isolated worktree."""
        if self.path.exists():
            return self.path
        self.repo.worktree_add(
            self.path, self.branch, self.base_ref, existing=self.repo.branch_exists(self.branch)
        )
        return self.path

    def remove(self, worktree_path_arg: Path | str | None = None) -> None:
        """Remove this task's worktree; safe when already gone."""
        self.repo.worktree_remove(self._resolve_path(worktree_path_arg))

    def cleanup(self, worktree_path_arg: Path | str | None = None) -> None:
        """Remove this task's worktree, swallowing errors when already gone."""
        with contextlib.suppress(WorktreeError, OSError):
            self.remove(worktree_path_arg)

    def delete_branch(self) -> None:
        """Delete this task's isolation branch; best effort."""
        self.repo.run("branch", "-D", self.branch)

    def base_status(self) -> RepoStatus:
        """Classify the base repo's tracked-file dirtiness."""
        return classify_status(self.repo.status_porcelain(untracked=False))

    def worktree_status(self, worktree_path_arg: Path | str | None = None) -> RepoStatus:
        """Classify a worktree's status (staged, unstaged, untracked, ahead)."""
        wt = GitRepo(self._resolve_path(worktree_path_arg))
        porcelain = wt.status_porcelain()
        return classify_status(porcelain, wt.rev_list(f"{self.base_ref}..HEAD"))

    def merge_to_base(self) -> MergeResult:
        """Merge this task's branch into the base ref (pure plan + execute)."""
        plan = plan_merge(self.base_status(), self.branch, self.base_ref)
        if plan is None:
            return MergeResult(ok=False, conflict=False, message="base repo dirty; merge manually")
        return self._execute(plan)

    def _execute(self, plan: list[MergeStep]) -> MergeResult:
        """Run a merge plan step by step, aborting cleanly on conflict."""
        for step in plan:
            if step is MergeStep.CHECKOUT_BASE:
                result = self.repo.run("checkout", self.base_ref)
                if result.returncode != 0:
                    return MergeResult(ok=False, conflict=False, message=result.stderr)
            elif step is MergeStep.FF_ONLY:
                if self.repo.run("merge", "--ff-only", self.branch).returncode == 0:
                    return MergeResult(ok=True, conflict=False, message="merged")
            elif step is MergeStep.MERGE_NO_FF:
                result = self.repo.run(
                    "merge", "--no-ff", self.branch, "-m", f"merge {self.branch}"
                )
                if result.returncode == 0:
                    return MergeResult(ok=True, conflict=False, message="merged")
                unmerged = self.repo.run("ls-files", "-u").stdout
                if is_merge_conflict(result.stdout + result.stderr, unmerged):
                    self.repo.run("merge", "--abort")
                    return MergeResult(ok=False, conflict=True, message=result.stderr)
                return MergeResult(ok=False, conflict=False, message=result.stderr)
        return MergeResult(ok=False, conflict=False, message="empty merge plan")

    def _resolve_path(self, worktree_path_arg: Path | str | None) -> Path:
        """The explicit worktree path, else this task's path (legacy fallback)."""
        if worktree_path_arg is not None:
            return Path(worktree_path_arg)
        if self.path.exists():
            return self.path
        return worktree_path(self.task_id, fleet_home=self.fleet_home)


def _for_task(
    repo_root: Path | str, task_id: str, base_ref: str = "main", fleet_home: Path | None = None
) -> TaskWorktree:
    """Build the TaskWorktree for one (repo, task) pair."""
    return TaskWorktree(
        repo=GitRepo(Path(repo_root)), task_id=task_id, base_ref=base_ref, fleet_home=fleet_home
    )


def create_worktree(
    repo_root: Path | str,
    task_id: str,
    base_ref: str = "main",
    fleet_home: Path | None = None,
) -> Path:
    """Create (or reuse) the isolated worktree for *task_id*."""
    return _for_task(repo_root, task_id, base_ref, fleet_home).create()


def remove_worktree(
    repo_root: Path | str,
    task_id: str,
    worktree_path_arg: Path | str | None = None,
    fleet_home: Path | None = None,
) -> None:
    """Remove the worktree for *task_id*; safe when already gone."""
    _for_task(repo_root, task_id, fleet_home=fleet_home).remove(worktree_path_arg)


def cleanup_worktree(
    repo_root: Path | str,
    task_id: str,
    worktree_path_arg: Path | str | None = None,
    fleet_home: Path | None = None,
) -> None:
    """Remove the worktree for *task_id* if it exists; safe at shutdown."""
    _for_task(repo_root, task_id, fleet_home=fleet_home).cleanup(worktree_path_arg)


def delete_branch(repo_root: Path | str, task_id: str) -> None:
    """Delete ``fleet/<task_id>`` after a successful merge; best effort."""
    _for_task(repo_root, task_id).delete_branch()


def is_repo_dirty(repo_root: Path | str) -> bool:
    """True when *repo_root* has uncommitted changes (tracked files)."""
    try:
        result = GitRepo(Path(repo_root)).run("status", "--porcelain", "--untracked-files=no")
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
        result = GitRepo(Path(worktree_path_arg)).run("status", "--porcelain")
    except (OSError, subprocess.SubprocessError):
        return True
    if result.returncode != 0:
        return True
    return bool(result.stdout.strip())


def is_committed_clean(worktree_path_arg: Path | str, base_ref: str = "main") -> bool:
    """True when the worktree is clean AND its HEAD advanced past *base_ref*."""
    try:
        wt = GitRepo(Path(worktree_path_arg))
        porcelain = wt.status_porcelain()
        if porcelain.strip():
            return False
        head = wt.rev_parse("HEAD").strip()
        base = wt.rev_parse(base_ref).strip()
        if not head or not base or head == base:
            return False
        return is_ahead(wt.rev_list(f"{base_ref}..HEAD"))
    except (OSError, subprocess.SubprocessError):
        return False


def merge_to_base(
    repo_root: Path | str,
    task_id: str,
    base_ref: str = "main",
) -> MergeResult:
    """Merge ``fleet/<task_id>`` into *base_ref* inside *repo_root*."""
    return _for_task(repo_root, task_id, base_ref).merge_to_base()


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
            argv, cwd=str(cwd), capture_output=True, text=True, timeout=timeout_sec, check=False
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
