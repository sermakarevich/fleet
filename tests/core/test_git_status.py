"""Tests for core/git_status.py. Mirrors the source path."""

from __future__ import annotations

from fleet.core.git_status import RepoStatus, classify_status, is_ahead, is_merge_conflict


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
