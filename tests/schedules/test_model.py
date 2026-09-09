"""Tests for `schedules.model` (records, templates, validation)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from fleet.schedules.cron import CronError
from fleet.schedules.model import (
    OverlapPolicy,
    Schedule,
    ScheduleRun,
    TargetKind,
    Trigger,
    new_id,
    render,
)


def _schedule(**overrides: object) -> Schedule:
    base: dict[str, object] = {
        "id": "sch-abc123",
        "name": "triage",
        "cron": "0 9 * * 1-5",
        "timezone": "UTC",
        "title": "Triage {name} #{n} on {date} at {time}",
        "created_at": "2026-09-09T00:00:00+00:00",
        "updated_at": "2026-09-09T00:00:00+00:00",
    }
    base.update(overrides)
    return Schedule.from_dict(base)  # type: ignore[arg-type]


def test_round_trip() -> None:
    schedule = _schedule(cwd="/tmp/x", coder="opencode", model="m", priority=1)
    clone = Schedule.from_dict(schedule.to_dict())
    assert clone == schedule


def test_defaults() -> None:
    schedule = _schedule()
    assert schedule.enabled is True
    assert schedule.overlap == OverlapPolicy.skip
    assert schedule.priority == 2
    assert schedule.description == ""


def test_unknown_keys_ignored() -> None:
    data = _schedule().to_dict()
    data["future_field"] = "whatever"
    assert Schedule.from_dict(data) == _schedule()


def test_enums_coerced() -> None:
    data = _schedule().to_dict()
    data["overlap"] = "queue"
    assert Schedule.from_dict(data).overlap == OverlapPolicy.queue


def test_bad_enum_raises() -> None:
    data = _schedule().to_dict()
    data["overlap"] = "replace"
    with pytest.raises(ValueError, match="overlap"):
        Schedule.from_dict(data)


def test_bad_cron_raises() -> None:
    data = _schedule().to_dict()
    data["cron"] = "99 * * * *"
    with pytest.raises(CronError):
        Schedule.from_dict(data)


def test_bad_timezone_raises() -> None:
    data = _schedule().to_dict()
    data["timezone"] = "Mars/Olympus"
    with pytest.raises(CronError, match="timezone"):
        Schedule.from_dict(data)


def test_render_known_placeholders() -> None:
    schedule = _schedule()
    when = datetime(2026, 9, 9, 7, 0, tzinfo=UTC)
    assert render(schedule.title, schedule, 12, when) == "Triage triage #12 on 2026-09-09 at 07:00"


def test_render_zone_local_time() -> None:
    schedule = _schedule(timezone="Europe/Warsaw")
    when = datetime(2026, 7, 1, 7, 0, tzinfo=UTC)  # 09:00 in Warsaw
    assert render("{date} {time}", schedule, 1, when) == "2026-07-01 09:00"


def test_render_unknown_placeholder_untouched() -> None:
    schedule = _schedule()
    when = datetime(2026, 9, 9, 7, 0, tzinfo=UTC)
    assert render("hello {owner}, run {n}", schedule, 3, when) == "hello {owner}, run 3"


def test_render_never_raises() -> None:
    schedule = _schedule()
    assert render("{unclosed", schedule, 1, datetime(2026, 9, 9, tzinfo=UTC)) == "{unclosed"


def test_new_id_shape() -> None:
    first, second = new_id(), new_id()
    assert first.startswith("sch-") and len(first) == 10
    assert first != second
    body = first.removeprefix("sch-")
    assert all(char in "0123456789abcdef" for char in body)


def test_run_round_trip() -> None:
    run = ScheduleRun(
        schedule_id="sch-abc123",
        n=4,
        scheduled_for="2026-09-09T09:00:00+00:00",
        fired_at="2026-09-09T09:00:05+00:00",
        trigger=Trigger.cron,
        task_id="fleet-abc",
        skipped=False,
    )
    clone = ScheduleRun.from_dict(run.to_dict())
    assert clone == run
    assert clone.reason == ""


def test_run_bad_trigger_raises() -> None:
    data = ScheduleRun(
        schedule_id="s",
        n=1,
        scheduled_for="x",
        fired_at="y",
        trigger=Trigger.manual,
        task_id=None,
        skipped=True,
        reason="overlap",
    ).to_dict()
    data["trigger"] = "someday"
    with pytest.raises(ValueError, match="trigger"):
        ScheduleRun.from_dict(data)


def test_workflow_target_round_trip() -> None:
    """A workflow schedule keeps its target and workflow id through JSON."""
    schedule = _schedule(target="workflow", workflow_id="wf-test0001", title="")
    assert schedule.target == TargetKind.workflow
    assert schedule.workflow_id == "wf-test0001"
    assert Schedule.from_dict(schedule.to_dict()) == schedule


def test_workflow_target_requires_workflow_id() -> None:
    """A workflow schedule without a workflow id is rejected."""
    with pytest.raises(ValueError, match="workflow_id"):
        _schedule(target="workflow", title="")


def test_workflow_target_needs_no_title() -> None:
    """A workflow schedule may leave the task title empty."""
    assert _schedule(target="workflow", workflow_id="wf-test0001", title="").title == ""


def test_task_target_requires_title() -> None:
    """A task schedule without a title is rejected."""
    with pytest.raises(ValueError, match="title"):
        _schedule(title="")


def test_bad_target_raises() -> None:
    """An unknown target value names the target field."""
    with pytest.raises(ValueError, match="target"):
        _schedule(target="fleet")


def test_old_schedule_json_without_target_loads() -> None:
    """Files written before targets existed load as task schedules."""
    data = _schedule().to_dict()
    del data["target"]
    data.pop("workflow_id", None)
    schedule = Schedule.from_dict(data)
    assert schedule.target == TargetKind.task
    assert schedule.workflow_id is None


def test_old_run_json_without_workflow_run_id_loads() -> None:
    """Run lines written before workflow runs load with a null run id."""
    run = ScheduleRun(
        schedule_id="sch-abc123",
        n=1,
        scheduled_for="2026-09-09T09:00:00+00:00",
        fired_at="2026-09-09T09:00:05+00:00",
        trigger=Trigger.cron,
        task_id="fleet-abc",
        skipped=False,
    )
    data = run.to_dict()
    del data["workflow_run_id"]
    assert ScheduleRun.from_dict(data) == run
