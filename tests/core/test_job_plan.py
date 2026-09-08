"""Tests for core/job_plan.py. Mirrors the source path."""

import pytest

from fleet.core.job_plan import observer_rounds, validate_followups


def _spec(title: str, **kw) -> dict:
    base = {"title": title, "body": f"body of {title}", "depends_on": []}
    base.update(kw)
    return base


def test_valid_single_followup() -> None:
    specs = validate_followups([_spec("fix tests")], max_followups=10)
    assert specs == [
        {"title": "fix tests", "body": "body of fix tests", "cwd": None, "depends_on": []}
    ]


def test_valid_chain_resolves_sibling_titles() -> None:
    specs = validate_followups(
        [_spec("a"), _spec("b", depends_on=["a"])], max_followups=10
    )
    assert specs[1]["depends_on"] == ["a"]


def test_non_list_rejected() -> None:
    with pytest.raises(ValueError, match="must be a list"):
        validate_followups({"title": "x"}, max_followups=10)  # type: ignore[arg-type]


def test_over_max_rejected() -> None:
    with pytest.raises(ValueError, match="too many"):
        validate_followups([_spec("a"), _spec("b")], max_followups=1)


def test_blank_title_rejected() -> None:
    with pytest.raises(ValueError, match="blank title"):
        validate_followups([{"title": "  "}], max_followups=10)


def test_duplicate_titles_rejected() -> None:
    with pytest.raises(ValueError, match="unique"):
        validate_followups([_spec("a"), _spec("a")], max_followups=10)


def test_unknown_dependency_rejected() -> None:
    with pytest.raises(ValueError, match="unknown"):
        validate_followups([_spec("a", depends_on=["ghost"])], max_followups=10)


def test_self_dependency_rejected() -> None:
    with pytest.raises(ValueError, match="itself"):
        validate_followups([_spec("a", depends_on=["a"])], max_followups=10)


def test_dependency_cycle_rejected() -> None:
    with pytest.raises(ValueError, match="cycle"):
        validate_followups(
            [_spec("a", depends_on=["b"]), _spec("b", depends_on=["a"])],
            max_followups=10,
        )


def _row(outcome: str, worker: str | None = "observer") -> dict:
    return {"n": 1, "outcome": outcome, "worker": worker, "kind": "work"}


def test_observer_rounds_counts_partial_observer_attempts() -> None:
    history = [_row("partial"), _row("partial"), _row("success")]
    assert observer_rounds(history) == 2


def test_observer_rounds_ignores_other_workers() -> None:
    history = [_row("partial", worker="task.fresh"), _row("partial")]
    assert observer_rounds(history) == 1


def test_observer_rounds_counts_untagged_legacy_rows() -> None:
    # Rows written before spawn tagged worker names carry None; on an epic
    # bead those can only be observer runs.
    assert observer_rounds([_row("partial", worker=None)]) == 1


def test_observer_rounds_ignores_waiting_rows() -> None:
    history = [_row("waiting"), _row("partial")]
    assert observer_rounds(history) == 1
