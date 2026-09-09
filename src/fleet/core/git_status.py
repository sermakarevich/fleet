"""Pure git-output classifiers: text in, facts out, no subprocess.

Called by ``orchestrator/worktree.py`` (and its ``GitRepo`` wrapper), which
runs git and hands the raw stdout here. Tests assert on literal
``git status --porcelain`` / ``git rev-list`` strings, never on repos.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RepoStatus:
    """What ``git status --porcelain`` says about a checkout."""

    dirty: bool
    untracked: bool
    ahead: bool


def classify_status(porcelain_text: str, rev_list_text: str = "") -> RepoStatus:
    """Classify ``git status --porcelain`` output into a RepoStatus.

    Any non-blank line means dirty; a line starting with ``??`` means
    untracked files are present; *rev_list_text* (the raw
    ``git rev-list --count`` output) marks the checkout ahead when its
    count is above zero.
    """
    dirty = bool(porcelain_text.strip())
    untracked = any(line.startswith("??") for line in porcelain_text.splitlines() if line.strip())
    return RepoStatus(dirty=dirty, untracked=untracked, ahead=is_ahead(rev_list_text))


def is_ahead(rev_list_text: str) -> bool:
    """True when ``git rev-list --count <base>..HEAD`` output counts above zero."""
    try:
        return int(rev_list_text.strip() or "0") > 0
    except ValueError:
        return False


def is_merge_conflict(combined_output: str, unmerged_files: str) -> bool:
    """True when a failed merge means conflict (not some other git error)."""
    if "CONFLICT" in combined_output:
        return True
    return bool(unmerged_files.strip())
