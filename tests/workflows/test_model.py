"""Model tests: validation rules, dependencies, defaults, dict round trip."""

from __future__ import annotations

import re

import pytest

from fleet.core.errors import WorkflowInvalid
from fleet.workflows.model import (
    STEP_STATE_OF_TASK_STATUS,
    Defaults,
    RunStatus,
    Stage,
    Step,
    StepRun,
    StepState,
    Trigger,
    Workflow,
    WorkflowInput,
    WorkflowRun,
    dependencies_of,
    effective,
    ensure_valid,
    new_id,
    new_run_id,
    step_state_of,
    validate,
)


def _workflow(**overrides) -> Workflow:
    """Build a small valid workflow, overridable per test."""
    stages = (
        Stage(name="first", steps=(Step(name="collect", title="Collect"),)),
        Stage(
            name="second",
            steps=(
                Step(name="impl-a", title="Implement A"),
                Step(name="impl-b", title="Implement B"),
            ),
        ),
    )
    base: dict = {
        "id": "wf-test0001",
        "name": "demo",
        "description": "d",
        "defaults": Defaults(),
        "stages": stages,
        "created_at": "2026-09-09T00:00:00Z",
        "updated_at": "2026-09-09T00:00:00Z",
    }
    base.update(overrides)
    return Workflow(**base)


def test_validate_accepts_good_workflow() -> None:
    assert validate(_workflow()) == []


def test_validate_empty_stages() -> None:
    assert any("stage" in p for p in validate(_workflow(stages=())))


def test_validate_stage_without_steps() -> None:
    wf = _workflow(stages=(Stage(name="empty", steps=()),))
    assert any("empty" in p for p in validate(wf))


def test_validate_bad_step_name() -> None:
    wf = _workflow(stages=(Stage(name="s", steps=(Step(name="Bad Name!", title="T"),)),))
    assert any("Bad Name!" in p for p in validate(wf))


def test_validate_duplicate_step_names() -> None:
    wf = _workflow(
        stages=(
            Stage(name="a", steps=(Step(name="dup", title="T"),)),
            Stage(name="b", steps=(Step(name="dup", title="T"),)),
        )
    )
    assert any("duplicate" in p for p in validate(wf))


def test_validate_needs_unknown_step() -> None:
    wf = _workflow(
        stages=(
            Stage(name="a", steps=(Step(name="one", title="T"),)),
            Stage(name="b", steps=(Step(name="two", title="T", needs=("ghost",)),)),
        )
    )
    assert any("ghost" in p for p in validate(wf))


def test_validate_needs_same_stage() -> None:
    wf = _workflow(
        stages=(
            Stage(
                name="a",
                steps=(
                    Step(name="one", title="T"),
                    Step(name="two", title="T", needs=("one",)),
                ),
            ),
        )
    )
    assert any("same or a later stage" in p for p in validate(wf))


def test_validate_needs_later_stage() -> None:
    wf = _workflow(
        stages=(
            Stage(name="a", steps=(Step(name="one", title="T", needs=("two",)),)),
            Stage(name="b", steps=(Step(name="two", title="T"),)),
        )
    )
    assert any("same or a later stage" in p for p in validate(wf))


def test_validate_priority_outside_range() -> None:
    wf = _workflow(stages=(Stage(name="a", steps=(Step(name="one", title="T", priority=9),)),))
    assert any("priority" in p for p in validate(wf))


def test_validate_defaults_priority_outside_range() -> None:
    wf = _workflow(defaults=Defaults(priority=7))
    assert any("priority" in p for p in validate(wf))


def test_validate_empty_title() -> None:
    wf = _workflow(stages=(Stage(name="a", steps=(Step(name="one", title=""),)),))
    assert any("title" in p for p in validate(wf))


def test_ensure_valid_raises_with_problems() -> None:
    with pytest.raises(WorkflowInvalid) as exc:
        ensure_valid(_workflow(stages=()))
    assert exc.value.problems


def test_ensure_valid_returns_workflow() -> None:
    wf = _workflow()
    assert ensure_valid(wf) is wf


def test_dependencies_of_defaults_to_fan_in() -> None:
    wf = _workflow()
    assert dependencies_of(wf, 1, wf.stages[1].steps[0]) == ("collect",)


def test_dependencies_of_first_stage_empty() -> None:
    wf = _workflow()
    assert dependencies_of(wf, 0, wf.stages[0].steps[0]) == ()


def test_dependencies_of_explicit_needs() -> None:
    wf = _workflow()
    step = Step(name="fast", title="T", needs=("collect",))
    assert dependencies_of(wf, 1, step) == ("collect",)


def test_effective_fills_from_defaults() -> None:
    defaults = Defaults(cwd="/repo", coder="opencode", model="m", priority=1)
    filled = effective(Step(name="s", title="T"), defaults)
    assert (filled.cwd, filled.coder, filled.model, filled.priority) == (
        "/repo",
        "opencode",
        "m",
        1,
    )


def test_effective_keeps_step_values() -> None:
    defaults = Defaults(cwd="/repo", coder="opencode", model="m", priority=1)
    step = Step(name="s", title="T", cwd="/other", coder="claude", priority=3)
    filled = effective(step, defaults)
    assert (filled.cwd, filled.coder, filled.priority) == ("/other", "claude", 3)


def test_dict_round_trip() -> None:
    wf = _workflow()
    assert Workflow.from_dict(wf.to_dict()) == wf


def test_run_and_step_run_dict_round_trip() -> None:
    wf = _workflow()
    run = WorkflowRun(
        id="wfr-test0001",
        workflow_id=wf.id,
        n=1,
        trigger=Trigger.manual,
        schedule_id=None,
        spec=wf,
        status=RunStatus.running,
        started_at="2026-09-09T00:00:00Z",
    )
    assert WorkflowRun.from_dict(run.to_dict()) == run
    step_run = StepRun(
        run_id=run.id,
        step_name="collect",
        stage_index=0,
        task_id="t1",
        task_status="open",
        updated_at="2026-09-09T00:00:00Z",
    )
    assert StepRun.from_dict(step_run.to_dict()) == step_run


def test_step_state_table_matches_adr() -> None:
    expected = {
        "closed": StepState.done,
        "blocked": StepState.attention,
        "in_progress": StepState.running,
        "open": StepState.waiting,
        "deferred": StepState.waiting,
    }
    assert len(STEP_STATE_OF_TASK_STATUS) == len(expected)
    for task_status, state in expected.items():
        assert STEP_STATE_OF_TASK_STATUS[task_status] is state
    assert step_state_of("closed") is StepState.done
    assert step_state_of("mystery") is StepState.waiting


def test_new_ids_shape() -> None:
    assert re.fullmatch(r"wf-[0-9a-z]{8}", new_id())
    assert re.fullmatch(r"wfr-[0-9a-z]{8}", new_run_id())
    assert new_id() != new_id()


def test_validate_bad_input_name() -> None:
    wf = _workflow(inputs=(WorkflowInput(name="Bad Name!"),))
    assert any("Bad Name!" in p for p in validate(wf))


def test_validate_duplicate_input_names() -> None:
    wf = _workflow(
        inputs=(WorkflowInput(name="url"), WorkflowInput(name="url", default="x")),
    )
    assert any("duplicate" in p for p in validate(wf))


def test_validate_required_input_with_default() -> None:
    wf = _workflow(inputs=(WorkflowInput(name="url", required=True, default="x"),))
    assert any("url" in p and "default" in p for p in validate(wf))


def test_validate_optional_input_with_default_ok() -> None:
    wf = _workflow(
        inputs=(
            WorkflowInput(name="url", required=True),
            WorkflowInput(name="focus", default="methods"),
        )
    )
    assert validate(wf) == []


def test_validate_bad_step_isolation() -> None:
    wf = _workflow(
        stages=(Stage(name="a", steps=(Step(name="one", title="T", isolation="vault"),)),)
    )
    assert any("isolation" in p for p in validate(wf))


def test_validate_bad_defaults_isolation() -> None:
    wf = _workflow(defaults=Defaults(isolation="vault"))
    assert any("isolation" in p for p in validate(wf))


def test_validate_isolation_none_ok() -> None:
    wf = _workflow(
        defaults=Defaults(isolation="worktree"),
        stages=(Stage(name="a", steps=(Step(name="one", title="T", isolation="none"),)),),
    )
    assert validate(wf) == []


def test_effective_fills_isolation_from_defaults() -> None:
    filled = effective(Step(name="s", title="T"), Defaults(isolation="none"))
    assert filled.isolation == "none"


def test_effective_keeps_step_isolation() -> None:
    filled = effective(Step(name="s", title="T", isolation="none"), Defaults(isolation="worktree"))
    assert filled.isolation == "none"


def test_dict_round_trip_with_inputs_and_isolation() -> None:
    wf = _workflow(
        defaults=Defaults(isolation="worktree"),
        inputs=(WorkflowInput(name="url", description="U", required=True),),
        stages=(
            Stage(
                name="a",
                steps=(Step(name="one", title="T", isolation="none"),),
            ),
        ),
    )
    assert Workflow.from_dict(wf.to_dict()) == wf


def test_run_dict_round_trip_with_inputs() -> None:
    wf = _workflow()
    run = WorkflowRun(
        id="wfr-test0002",
        workflow_id=wf.id,
        n=1,
        trigger=Trigger.manual,
        schedule_id=None,
        spec=wf,
        status=RunStatus.running,
        started_at="2026-09-09T00:00:00Z",
        inputs={"url": "https://example.test/paper"},
    )
    assert WorkflowRun.from_dict(run.to_dict()) == run
