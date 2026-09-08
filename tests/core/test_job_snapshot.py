"""Tests for core/job_snapshot.py. Mirrors the source path."""

from __future__ import annotations

from fleet.core.job_phase import phase
from fleet.core.job_snapshot import JobSnapshot


def test_defaults_match_phase_research() -> None:
    assert phase(JobSnapshot()) == "research"


def test_to_dict_round_trip() -> None:
    snap = JobSnapshot(has_research=True, has_tasks=True, gate_enabled=False, has_children=True)
    assert JobSnapshot.from_dict(snap.to_dict()) == snap


def test_from_dict_defaults() -> None:
    assert JobSnapshot.from_dict({}) == JobSnapshot()
    assert JobSnapshot.from_dict({"has_research": 1, "gate_enabled": 0}) == JobSnapshot(
        has_research=True, gate_enabled=False
    )


def test_snapshot_drives_phase_table() -> None:
    assert phase(JobSnapshot(has_research=True)) == "design"
    assert phase(JobSnapshot(has_research=True, has_tasks=True)) == "gate"
    assert phase(JobSnapshot(has_research=True, has_tasks=True, approved=True)) == "spawn"
    assert phase(JobSnapshot(has_research=True, has_tasks=True, has_children=True)) == "observe"
