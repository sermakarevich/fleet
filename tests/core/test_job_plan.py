"""Tests for core/job_plan.py. Mirrors the source path."""

import pytest

from fleet.core.job_plan import observer_rounds, validate_followups, validate_tasks


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


def test_observer_rounds_counts_job_observe_partials() -> None:
    history = [_row("partial", worker="job.observe"), _row("partial", worker="job.design")]
    assert observer_rounds(history) == 1


# ---------------------------------------------------------------------------
# validate_tasks
# ---------------------------------------------------------------------------


def _task(key: str, **kw) -> dict:
    base = {"key": key, "title": f"title {key}", "body": f"body {key}", "depends_on": []}
    base.update(kw)
    return base


def _doc(*tasks: dict) -> dict:
    return {"tasks": list(tasks)}


def test_validate_tasks_ok() -> None:
    assert validate_tasks(_doc(_task("t0"), _task("t1", depends_on=["t0"]))) == []


def test_validate_tasks_not_an_object() -> None:
    assert validate_tasks([]) != []
    assert validate_tasks({"nope": []}) != []


def test_validate_tasks_empty_and_over_max() -> None:
    assert validate_tasks({"tasks": []}) != []
    many = _doc(*(_task(f"t{i}") for i in range(3)))
    assert validate_tasks(many, max_children=2) == [
        "too many tasks (3 > 2)"
    ]


def test_validate_tasks_blank_key_and_duplicates() -> None:
    assert validate_tasks(_doc({"title": "x", "body": "y"})) != []
    assert validate_tasks(_doc(_task("a"), _task("a"))) == [
        "task keys must be unique"
    ]


def test_validate_tasks_title_rules() -> None:
    assert validate_tasks(_doc(_task("a", title="  "))) == [
        "task 'a' has a blank title"
    ]
    assert validate_tasks(_doc(_task("a", title="x" * 121))) == [
        "task 'a' title exceeds 120 chars"
    ]


def test_validate_tasks_blank_body() -> None:
    assert validate_tasks(_doc(_task("a", body="  "))) == [
        "task 'a' has a blank body"
    ]


def test_validate_tasks_unknown_self_and_cycle() -> None:
    assert validate_tasks(_doc(_task("a", depends_on=["ghost"]))) == [
        "task 'a' depends on unknown 'ghost'"
    ]
    assert validate_tasks(_doc(_task("a", depends_on=["a"]))) == [
        "task 'a' cannot depend on itself"
    ]
    errors = validate_tasks(
        _doc(_task("a", depends_on=["b"]), _task("b", depends_on=["a"]))
    )
    assert len(errors) == 1 and "cycle" in errors[0]
