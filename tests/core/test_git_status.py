"""Tests for core/git_status.py. Mirrors the source path."""

from __future__ import annotations

from fleet.core.git_status import (
    RepoStatus,
    classify_status,
    is_ahead,
    is_merge_conflict,
    is_scaffold_path,
    strip_scaffold_lines,
)


def test_clean_tree_is_not_dirty() -> None:
    """Empty porcelain means a clean checkout with nothing ahead."""
    assert classify_status("") == RepoStatus(dirty=False, untracked=False, ahead=False)


def test_tracked_modification_is_dirty_not_untracked() -> None:
    """Staged/unstaged edits mark dirty without the untracked flag."""
    status = classify_status("M  fleet/core/clock.py\n M fleet/core/leases.py\n")
    assert status.dirty
    assert not status.untracked


def test_question_marks_mean_untracked() -> None:
    """'??' lines mark untracked files present (and the tree dirty)."""
    status = classify_status("?? new-file.txt\n")
    assert status.dirty
    assert status.untracked


def test_rev_list_count_marks_ahead() -> None:
    """A nonzero rev-list count marks the checkout ahead of base."""
    assert classify_status("", "3\n").ahead
    assert classify_status("M x\n", "1\n").ahead


def test_is_ahead_rejects_zero_blank_and_garbage() -> None:
    """Zero, blank, and unparsable counts are not ahead."""
    assert not is_ahead("0\n")
    assert not is_ahead("")
    assert not is_ahead("not-a-number\n")


def test_merge_conflict_from_output_or_unmerged_files() -> None:
    """CONFLICT text or leftover unmerged files both mean conflict."""
    assert is_merge_conflict("Auto-merging f\nCONFLICT (content): Merge conflict in f\n", "")
    assert is_merge_conflict("merge failed: unrelated histories\n", "100644 abc 1\tf\n")
    assert not is_merge_conflict("merge failed: unrelated histories\n", "")


def test_scaffold_only_is_clean() -> None:
    """Fleet scaffolding (.claude/, .fleet/) alone is not worker dirt."""
    status = classify_status("?? .claude/settings.json\n?? .fleet/hooks/precompact.sh\n")
    assert status == RepoStatus(dirty=False, untracked=False, ahead=False)


def test_scaffold_alongside_real_changes_is_dirty() -> None:
    """Scaffolding is ignored but real changes still count."""
    status = classify_status("?? .claude/settings.json\n?? real-work.txt\n")
    assert status.dirty
    assert status.untracked
    status = classify_status("?? .fleet/hooks/a.sh\n M src/code.py\n")
    assert status.dirty
    assert not status.untracked


def test_tracked_scaffold_modification_is_ignored() -> None:
    """A fleet-merged .claude/settings.json edit is not worker dirt."""
    assert classify_status(" M .claude/settings.json\n") == RepoStatus(
        dirty=False, untracked=False, ahead=False
    )


def test_lookalike_paths_are_not_scaffold() -> None:
    """Only top-level .claude/ and .fleet/ are ignored, not name lookalikes."""
    assert not is_scaffold_path(".claudefoo/bar.txt")
    assert not is_scaffold_path("sub/.fleet/x.sh")
    assert not is_scaffold_path("src/.claude-notes.txt")
    assert is_scaffold_path(".fleet/hooks/a.sh")
    assert is_scaffold_path(".claude")
    assert classify_status("?? .claudefoo/bar.txt\n").dirty
    assert strip_scaffold_lines("") == ""
