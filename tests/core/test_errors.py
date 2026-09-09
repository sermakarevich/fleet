"""Typed-domain errors: one exception per meaning (ADR 0006 bead 18)."""

from __future__ import annotations

import pytest

from fleet.core.config import merge, parse
from fleet.core.context_window import parse_context_windows
from fleet.core.errors import (
    ConfigError,
    FleetError,
    PlanError,
    QuestionNotFound,
    WorktreeError,
)
from fleet.core.job_plan import validate_followups
from fleet.integrations.ask_human.store import Question, QuestionStore


def test_error_hierarchy() -> None:
    """Typed errors are FleetErrors and stay catchable as builtins."""
    assert issubclass(ConfigError, FleetError)
    assert issubclass(ConfigError, ValueError)
    assert issubclass(PlanError, FleetError)
    assert issubclass(PlanError, ValueError)
    assert issubclass(WorktreeError, FleetError)
    assert issubclass(WorktreeError, RuntimeError)
    assert issubclass(QuestionNotFound, FleetError)
    assert issubclass(QuestionNotFound, KeyError)


def test_config_errors() -> None:
    """Bad bools, isolation modes, keys, and windows raise ConfigError."""
    with pytest.raises(ConfigError):
        parse({"compaction_enabled": "sometimes"})
    with pytest.raises(ConfigError):
        parse({"isolation": "chroot"})
    with pytest.raises(ConfigError):
        merge({}, {"no_such_key": 1})
    with pytest.raises(ConfigError):
        parse_context_windows("model:not-a-number")
    with pytest.raises(ValueError):
        parse_context_windows("model:not-a-number")


def test_plan_errors() -> None:
    """Bad follow-up specs raise PlanError, still caught as ValueError."""
    with pytest.raises(PlanError):
        validate_followups("not-a-list", max_followups=3)  # type: ignore[arg-type]
    with pytest.raises(PlanError):
        validate_followups([{"title": ""}], max_followups=3)
    with pytest.raises(ValueError):
        validate_followups([{"title": ""}], max_followups=3)


def test_question_not_found(tmp_path) -> None:
    """Missing questions raise QuestionNotFound carrying the id."""
    store = QuestionStore(tmp_path / "q.db")
    with pytest.raises(QuestionNotFound) as exc_info:
        store.wait(store.create("ghost?") + "-missing", poll_interval=0.01)
    assert exc_info.value.qid
    with pytest.raises(KeyError):
        store.wait(store.create("ghost?") + "-missing", poll_interval=0.01)


def test_question_round_trip(tmp_path) -> None:
    """Rows come back as frozen Questions; dicts only at the JSON edge."""
    store = QuestionStore(tmp_path / "q.db")
    qid = store.ask("pick one", ["a", "b"], task_id="t-1", context="c")
    question = store.get(qid)
    assert isinstance(question, Question)
    assert question.id == qid
    assert question.get("task_id") == "t-1"
    assert question["context"] == "c"
    assert question.to_dict()["prompt"] == "pick one"
    pending = store.fetch_pending_for_task("t-1", "c")
    assert [q.id for q in pending] == [qid]
    with pytest.raises(AttributeError):
        question.status = "answered"  # type: ignore[misc]
