"""Tests for `schedules.firing` (due/overlap/catch-up decisions and the writer)."""

from __future__ import annotations

import json
import shlex
from datetime import datetime
from pathlib import Path

import pytest
import structlog

from fleet.beads.client import BdError
from fleet.beads.queue import Queue
from fleet.core.task import Task
from fleet.schedules.firing import (
    Action,
    Decision,
    decide,
    fire,
    fire_due,
    open_task,
    previous_task_status,
)
from fleet.schedules.model import Schedule, ScheduleRun, Trigger
from fleet.schedules.store import ScheduleStore
from tests.conftest import FakeQueue

CREATED = "2026-09-09T00:00:00+00:00"


def _schedule(**overrides) -> Schedule:
    """One every-minute schedule with fixed timestamps unless overridden."""
    data = {
        "id": "sch-abc123",
        "name": "nightly",
        "cron": "* * * * *",
        "title": "Run {name} #{n}",
        "description": "at {date} {time}",
        "created_at": CREATED,
        "updated_at": CREATED,
    }
    data.update(overrides)
    return Schedule.from_dict(data)


def _at(text: str) -> datetime:
    """Aware UTC datetime from an ISO string."""
    return datetime.fromisoformat(text)


def _cron_run(scheduled_for: str, n: int = 1, task_id: str | None = "fake-000") -> ScheduleRun:
    """One stored cron run for baselines and previous-task lookups."""
    return ScheduleRun(
        schedule_id="sch-abc123",
        n=n,
        scheduled_for=scheduled_for,
        fired_at=scheduled_for,
        trigger=Trigger.cron,
        task_id=task_id,
        skipped=task_id is None,
        reason="",
    )


def test_decide_table() -> None:
    """Decide outcomes across disabled, timing, catch-up, and overlap cases."""
    at0 = "2026-09-09T00:00:30+00:00"
    at1 = "2026-09-09T00:01:00+00:00"
    at3 = "2026-09-09T00:03:00+00:00"
    at3_late = "2026-09-09T00:03:30+00:00"
    at5 = "2026-09-09T00:05:00+00:00"
    at5_late = "2026-09-09T00:05:30+00:00"
    cases: list[tuple[str, Schedule, ScheduleRun | None, str | None, str, Action, str | None]] = [
        ("disabled waits", _schedule(enabled=False), None, None, at5_late, Action.wait, None),
        ("not yet due waits", _schedule(), None, None, at0, Action.wait, None),
        ("due once opens", _schedule(), None, None, at1, Action.open, at1),
        ("three missed coalesce to latest", _schedule(), None, None, at3_late, Action.open, at3),
        ("skip on open previous", _schedule(), None, "open", at1, Action.skip, at1),
        (
            "queue policy opens anyway",
            _schedule(overlap="queue"),
            None,
            "open",
            at1,
            Action.open,
            at1,
        ),
        ("previous closed opens", _schedule(), None, "closed", at1, Action.open, at1),
        (
            "baseline is last cron run",
            _schedule(),
            _cron_run(at5),
            None,
            at5_late,
            Action.wait,
            None,
        ),
    ]
    for label, schedule, last, status, now_raw, want_action, want_for in cases:
        got = decide(schedule, last, status, _at(now_raw))
        assert got.action is want_action, label
        assert (got.scheduled_for.isoformat() if got.scheduled_for else None) == want_for, label


def test_decide_reasons() -> None:
    """Wait/skip/open reasons name the next minute, the status, or due."""
    assert decide(_schedule(enabled=False), None, None, _at(CREATED)).reason == "disabled"
    waiting = decide(_schedule(), None, None, _at("2026-09-09T00:00:30+00:00"))
    assert waiting.reason == "next at 2026-09-09T00:01:00+00:00"
    skipped = decide(_schedule(), None, "in_progress", _at("2026-09-09T00:01:00+00:00"))
    assert skipped.reason == "previous task is in_progress"
    assert isinstance(skipped, Decision)
    opened = decide(_schedule(), None, None, _at("2026-09-09T00:01:00+00:00"))
    assert opened.reason == "due"


class RecordingQueue(FakeQueue):
    """FakeQueue that remembers the last create_task call."""

    def __init__(self, tasks: list[Task] | None = None) -> None:
        super().__init__(tasks)
        self.last_create: dict = {}

    def create_task(  # noqa: PLR0913, PLR0917  # mirrors Queue.create_task signature
        self,
        title: str,
        description: str | None = None,
        depends_on: list[str] | None = None,
        labels: list[str] | None = None,
        cwd: str | None = None,
        coder: str | None = None,
        model: str | None = None,
        worker: str | None = None,
        extra_args: str | None = None,
    ) -> Task:
        self.last_create = {
            "title": title,
            "description": description,
            "cwd": cwd,
            "coder": coder,
            "model": model,
            "extra_args": extra_args,
        }
        return super().create_task(
            title,
            description,
            depends_on,
            labels,
            cwd,
            coder,
            model,
            worker,
            extra_args,
        )


def test_open_task_passes_fields_and_extra_args() -> None:
    """open_task renders templates and encodes labels, priority, and metadata."""
    queue = RecordingQueue()
    schedule = _schedule(cwd="/repo", coder="opencode", model="m", priority=1)
    task_id = open_task(schedule, queue, 3, _at("2026-09-09T00:01:00+00:00"))
    assert task_id == "fake-000"
    assert queue.last_create["title"] == "Run nightly #3"
    assert queue.last_create["description"] == "at 2026-09-09 00:01"
    assert (queue.last_create["cwd"], queue.last_create["coder"], queue.last_create["model"]) == (
        "/repo",
        "opencode",
        "m",
    )
    extra = str(queue.last_create["extra_args"])
    assert "-p 1" in extra
    assert "recurring" in extra and "schedule:sch-abc123" in extra
    tokens = shlex.split(extra)
    meta = json.loads(tokens[tokens.index("--metadata") + 1])
    assert meta == {
        "fleet_schedule_id": "sch-abc123",
        "fleet_schedule_run": 3,
        "fleet_cwd": "/repo",
        "fleet_coder": "opencode",
        "fleet_model": "m",
    }


def test_open_task_omits_unset_metadata() -> None:
    """Metadata only carries fleet_cwd/coder/model when the schedule sets them."""
    queue = RecordingQueue()
    open_task(_schedule(), queue, 1, _at("2026-09-09T00:01:00+00:00"))
    tokens = shlex.split(str(queue.last_create["extra_args"]))
    meta = json.loads(tokens[tokens.index("--metadata") + 1])
    assert meta == {"fleet_schedule_id": "sch-abc123", "fleet_schedule_run": 1}


def test_previous_task_status(tmp_path: Path) -> None:
    """previous_task_status follows the newest run that opened a task."""
    store = ScheduleStore(tmp_path)
    queue = FakeQueue([Task(id="fake-000", title="T", description=None, status="in_progress")])
    store.append_run(_cron_run("2026-09-09T00:01:00+00:00", n=1, task_id="gone"))
    store.append_run(_cron_run("2026-09-09T00:02:00+00:00", n=2, task_id="fake-000"))
    assert previous_task_status(store, "sch-abc123", queue) == ("fake-000", "in_progress")
    assert previous_task_status(store, "sch-missing", queue) == (None, None)


def test_previous_task_status_gone_task_counts_as_closed(tmp_path: Path) -> None:
    """A BdError (task gone from the queue) reads as closed."""
    store = ScheduleStore(tmp_path)
    store.append_run(_cron_run("2026-09-09T00:01:00+00:00", n=1, task_id="gone"))
    assert previous_task_status(store, "sch-abc123", FakeQueue()) == ("gone", "closed")


def test_fire_cron_open_appends_numbered_run(tmp_path: Path) -> None:
    """fire() opens a task and stores run n with the cron trigger."""
    store = ScheduleStore(tmp_path)
    queue = RecordingQueue()
    run = fire(
        _schedule(),
        store=store,
        queue=queue,
        now=_at("2026-09-09T00:01:00+00:00"),
        trigger=Trigger.cron,
        scheduled_for=_at("2026-09-09T00:01:00+00:00"),
        reason="due",
    )
    assert (run.n, run.trigger, run.task_id, run.skipped, run.reason) == (
        1,
        Trigger.cron,
        "fake-000",
        False,
        "due",
    )
    assert store.run_count("sch-abc123") == 1


def test_fire_skip_records_no_task(tmp_path: Path) -> None:
    """A skip decision records task_id None without touching the queue."""
    store = ScheduleStore(tmp_path)
    queue = RecordingQueue()
    run = fire(
        _schedule(),
        store=store,
        queue=queue,
        now=_at("2026-09-09T00:01:00+00:00"),
        trigger=Trigger.cron,
        scheduled_for=_at("2026-09-09T00:01:00+00:00"),
        reason="previous task is open",
        skipped=True,
    )
    assert (run.task_id, run.skipped, run.n) == (None, True, 1)
    assert queue.last_create == {}


def test_fire_manual_always_opens(tmp_path: Path) -> None:
    """Manual runs use now as scheduled_for and ignore the overlap flag."""
    store = ScheduleStore(tmp_path)
    queue = RecordingQueue()
    now = _at("2026-09-09T00:01:30+00:00")
    run = fire(
        _schedule(),
        store=store,
        queue=queue,
        now=now,
        trigger=Trigger.manual,
        skipped=True,
        reason="run now",
    )
    assert (run.trigger, run.task_id, run.skipped, run.scheduled_for) == (
        Trigger.manual,
        "fake-000",
        False,
        now.isoformat(),
    )


class FailingQueue(RecordingQueue):
    """Queue that raises BdError for one schedule's title marker."""

    def create_task(  # noqa: PLR0913, PLR0917  # mirrors Queue.create_task signature
        self,
        title: str,
        description: str | None = None,
        depends_on: list[str] | None = None,
        labels: list[str] | None = None,
        cwd: str | None = None,
        coder: str | None = None,
        model: str | None = None,
        worker: str | None = None,
        extra_args: str | None = None,
    ) -> Task:
        if "boom" in title:
            raise BdError("bd create exploded")
        return super().create_task(
            title, description, depends_on, labels, cwd, coder, model, worker, extra_args
        )


def _log() -> structlog.typing.FilteringLogger:
    """Throwaway logger: fire_due only needs info/error methods."""
    return structlog.get_logger("test")


def test_fire_bd_error_records_skipped_and_reraises(tmp_path: Path) -> None:
    """A queue BdError becomes a skipped run, then reaches the caller."""
    store = ScheduleStore(tmp_path)
    schedule = _schedule(name="boom")
    with pytest.raises(BdError, match="exploded"):
        fire(
            schedule,
            store=store,
            queue=FailingQueue(),
            now=_at("2026-09-09T00:01:00+00:00"),
            trigger=Trigger.cron,
            scheduled_for=_at("2026-09-09T00:01:00+00:00"),
            reason="due",
        )
    (run,) = store.runs("sch-abc123")
    assert run.skipped and run.task_id is None and run.reason.startswith("bd error:")


def test_fire_due_continues_after_failure_and_baseline_moves(tmp_path: Path) -> None:
    """fire_due fires the healthy schedule, skips the broken one, then idles."""
    store = ScheduleStore(tmp_path)
    store.save(_schedule(id="sch-aaa001", name="apple"))
    store.save(_schedule(id="sch-zzz002", name="boom"))
    queue: Queue = FailingQueue()
    now = _at("2026-09-09T00:01:00+00:00")
    fired = fire_due(store=store, queue=queue, now=now, log=_log())
    assert [run.schedule_id for run in fired] == ["sch-aaa001"]
    (bad,) = store.runs("sch-zzz002")
    assert bad.skipped and bad.reason.startswith("bd error:")
    counts = {item.id: store.run_count(item.id) for item in store.list()}
    fired_again = fire_due(store=store, queue=queue, now=now, log=_log())
    assert fired_again == []
    assert {item.id: store.run_count(item.id) for item in store.list()} == counts


def test_fire_due_skip_moves_baseline(tmp_path: Path) -> None:
    """An overlap skip still advances the baseline, so the tick idles next."""
    store = ScheduleStore(tmp_path)
    store.save(_schedule())
    queue = FakeQueue([Task(id="fake-000", title="T", description=None, status="in_progress")])
    store.append_run(_cron_run("2026-09-09T00:00:00+00:00", n=1, task_id="fake-000"))
    now = _at("2026-09-09T00:01:00+00:00")
    (run,) = fire_due(store=store, queue=queue, now=now, log=_log())
    assert run.skipped and run.scheduled_for == "2026-09-09T00:01:00+00:00"
    assert fire_due(store=store, queue=queue, now=now, log=_log()) == []
