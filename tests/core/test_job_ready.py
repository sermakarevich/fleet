"""Tests for core/job_ready.py. Mirrors the source path."""

from fleet.core.job_ready import BeadSummary, children_terminal


def _kids(*statuses: str) -> list[BeadSummary]:
    return [BeadSummary(id=f"c-{i}", status=s) for i, s in enumerate(statuses)]


def test_all_closed_is_terminal() -> None:
    assert children_terminal(_kids("closed", "closed")) is True


def test_closed_and_blocked_is_terminal() -> None:
    assert children_terminal(_kids("closed", "blocked")) is True


def test_open_child_is_not_terminal() -> None:
    assert children_terminal(_kids("closed", "open")) is False


def test_in_progress_child_is_not_terminal() -> None:
    assert children_terminal(_kids("closed", "in_progress")) is False


def test_unknown_status_is_not_terminal() -> None:
    assert children_terminal(_kids("closed", "")) is False


def test_empty_is_vacuously_terminal() -> None:
    # Callers (claim) must still require a non-empty child list; the pure
    # rule alone is vacuously true.
    assert children_terminal([]) is True
