"""One place that shells out to git: ``GitRepo``.

Called by ``orchestrator/worktree.py`` (and only there). Every git
invocation in the orchestrator flows through ``GitRepo.run`` — the single
``subprocess.run(["git", "-C", ...])`` call site with ``GIT_TIMEOUT_SEC`` —
while output classification lives in ``core/git_status.py``.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from fleet.core.errors import WorktreeError
from fleet.core.limits import GIT_TIMEOUT_SEC


@dataclass(frozen=True, slots=True)
class GitRepo:
    """A git checkout plus the one way to run git inside it."""

    root: Path

    def run(self, *args: str, timeout: int = GIT_TIMEOUT_SEC) -> subprocess.CompletedProcess:
        """Run ``git -C <root> <args>``; the ONE git call site (never raises)."""
        try:
            return subprocess.run(
                ["git", "-C", str(self.root), *args],
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return subprocess.CompletedProcess(
                args=["git"], returncode=1, stdout="", stderr=str(exc)
            )

    def status_porcelain(self, untracked: bool = True) -> str:
        """Raw ``git status --porcelain`` output ("" when git fails)."""
        args = ["status", "--porcelain"]
        if not untracked:
            args.append("--untracked-files=no")
        result = self.run(*args)
        return result.stdout if result.returncode == 0 else ""

    def rev_list(self, spec: str) -> str:
        """Raw ``git rev-list --count <spec>`` output ("" when git fails)."""
        result = self.run("rev-list", "--count", spec)
        return result.stdout if result.returncode == 0 else ""

    def rev_parse(self, ref: str) -> str:
        """Raw ``git rev-parse <ref>`` output ("" when git fails)."""
        result = self.run("rev-parse", ref)
        return result.stdout if result.returncode == 0 else ""

    def branch_exists(self, branch: str) -> bool:
        """True when ``refs/heads/<branch>`` resolves in this repo."""
        return self.run("rev-parse", "--verify", f"refs/heads/{branch}").returncode == 0

    def worktree_add(self, path: Path, branch: str, base_ref: str, existing: bool) -> None:
        """Check out *branch* at *path* (new from *base_ref* unless *existing*)."""
        if existing:
            cmd: tuple[str, ...] = ("worktree", "add", str(path), branch)
        else:
            cmd = ("worktree", "add", str(path), "-b", branch, base_ref)
        result = self.run(*cmd, timeout=GIT_TIMEOUT_SEC)
        if result.returncode != 0:
            raise WorktreeError(f"git worktree add failed: {result.stderr}")

    def worktree_remove(self, path: Path) -> None:
        """Force-remove the worktree at *path*; raise WorktreeError when stuck."""
        result = self.run("worktree", "remove", "--force", str(path))
        if (
            result.returncode != 0
            and "does not exist" not in result.stderr
            and "is not a working tree" not in result.stderr
        ):
            raise WorktreeError(f"git worktree remove failed: {result.stderr}")

    def worktree_list(self) -> str:
        """Raw ``git worktree list --porcelain`` output ("" when git fails)."""
        result = self.run("worktree", "list", "--porcelain")
        return result.stdout if result.returncode == 0 else ""
