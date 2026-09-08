"""Tests for core/job_phase.py. Mirrors the source path."""

from fleet.core.job_phase import JobSnapshot, phase, phase_attempts, phase_failures


def _snap(**kw) -> JobSnapshot:
    base = {
        "has_research": False,
        "has_tasks": False,
        "gate_enabled": True,
        "approved": False,
        "has_children": False,
    }
    base.update(kw)
    return JobSnapshot(**base)


def test_no_research_is_research() -> None:
    assert phase(_snap()) == "research"


def test_research_without_tasks_is_design() -> None:
    assert phase(_snap(has_research=True)) == "design"


def test_tasks_without_approval_is_gate() -> None:
    assert phase(_snap(has_research=True, has_tasks=True)) == "gate"


def test_approved_without_children_is_spawn() -> None:
    assert phase(_snap(has_research=True, has_tasks=True, approved=True)) == "spawn"


def test_gate_off_without_children_is_spawn() -> None:
    assert phase(_snap(has_research=True, has_tasks=True, gate_enabled=False)) == "spawn"


def test_children_exist_is_observe() -> None:
    assert (
        phase(_snap(has_research=True, has_tasks=True, approved=True, has_children=True))
        == "observe"
    )


def test_children_win_over_pending_gate() -> None:
    # A crashed spawn that already created children resumes in observe,
    # never back in the gate.
    assert phase(_snap(has_research=True, has_tasks=True, has_children=True)) == "observe"


def test_phase_attempts_counts_phase_workers_only() -> None:
    history = [
        {"worker": "job.research", "outcome": "partial"},
        {"worker": "job.research", "outcome": "waiting"},
        {"worker": "job.design", "outcome": "partial"},
        {"worker": "observer", "outcome": "partial"},
    ]
    assert phase_attempts(history, "research") == 1
    assert phase_attempts(history, "design") == 1


def test_phase_failures_counts_failures_not_partials() -> None:
    history = [
        {"worker": "job.research", "outcome": "partial"},
        {"worker": "job.research", "outcome": "failure"},
        {"worker": "job.research", "outcome": "killed", "reason": "timeout"},
        {"worker": "job.research", "outcome": "killed", "reason": "manual_kill"},
    ]
    assert phase_failures(history, "research") == 2
