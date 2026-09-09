"""Tests for core/leases.py. Mirrors the source path."""

from __future__ import annotations

from fleet.core.leases import LeaseVerdict, classify_lease, is_orphan_dir, orphan_dirs


def _facts(**overrides):
    """Full LIVE facts; callers override the axis under test."""
    facts = {
        "has_attempt_dir": True,
        "has_run": True,
        "lease_stale": True,
        "pid_valid": True,
        "pid_dead": True,
        "attempt_ended": False,
    }
    facts.update(overrides)
    return facts


def test_fresh_lease_is_live() -> None:
    """A lease that is not stale stays live."""
    assert classify_lease(**_facts(lease_stale=False)) is LeaseVerdict.LIVE


def test_missing_attempt_or_run_is_not_ours() -> None:
    """Human-claimed beads (no attempt/run) can never be reclaimed."""
    assert classify_lease(**_facts(has_attempt_dir=False)) is LeaseVerdict.NOT_OURS
    assert classify_lease(**_facts(has_run=False)) is LeaseVerdict.NOT_OURS


def test_stale_lease_with_live_pid_only_warns() -> None:
    """A stale lease on a live pid warns; fleet never kills it."""
    assert classify_lease(**_facts(pid_dead=False)) is LeaseVerdict.STALE_PID_ALIVE


def test_unparseable_pid_is_not_ours() -> None:
    """Without a valid pid nothing can be proven, so nothing is reclaimed."""
    assert classify_lease(**_facts(pid_valid=False)) is LeaseVerdict.NOT_OURS


def test_stale_dead_pid_reclaims() -> None:
    """A stale lease on a dead pid is the one reclaimable case."""
    assert classify_lease(**_facts()) is LeaseVerdict.RECLAIM


def test_already_ended_attempt_is_not_ours() -> None:
    """An attempt that journaled its end belongs to the queue path now."""
    assert classify_lease(**_facts(attempt_ended=True)) is LeaseVerdict.NOT_OURS


def test_orphan_dir_keeps_live_paths_ids_and_suffixes() -> None:
    """Referenced paths, live ids, and <repo>-<id> dirs are never orphans."""
    live_paths = {"/wt/repo-t-1"}
    live_ids = {"t-1", "t-2"}
    assert not is_orphan_dir("repo-t-1", "/wt/repo-t-1", live_paths, live_ids)
    assert not is_orphan_dir("t-2", "/wt/t-2", live_paths, live_ids)
    assert not is_orphan_dir("other-t-1", "/wt/other-t-1", live_paths, live_ids)
    assert is_orphan_dir("repo-t-9", "/wt/repo-t-9", live_paths, live_ids)


def test_orphan_dirs_lists_only_dead_names() -> None:
    """orphan_dirs filters (name, resolved) pairs down to the dead ones."""
    resolved = [("t-1", "/wt/t-1"), ("repo-t-9", "/wt/repo-t-9")]
    assert orphan_dirs(resolved, {"/wt/t-1"}, {"t-1"}) == ["repo-t-9"]
