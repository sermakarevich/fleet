"""Tests for `schedules.store` (definitions and run history on disk)."""

from __future__ import annotations

from pathlib import Path

import pytest

from fleet.schedules.model import Schedule, ScheduleRun, Trigger
from fleet.schedules.store import ScheduleStore


def _schedule(schedule_id: str = "sch-abc123", name: str = "triage") -> Schedule:
    return Schedule.from_dict(
        {
            "id": schedule_id,
            "name": name,
            "cron": "0 9 * * 1-5",
            "title": "Triage {name} #{n}",
            "created_at": "2026-09-09T00:00:00+00:00",
            "updated_at": "2026-09-09T00:00:00+00:00",
        }
    )


def _run(
    schedule_id: str = "sch-abc123", n: int = 1, trigger: Trigger = Trigger.cron
) -> ScheduleRun:
    return ScheduleRun(
        schedule_id=schedule_id,
        n=n,
        scheduled_for="2026-09-09T09:00:00+00:00",
        fired_at="2026-09-09T09:00:05+00:00",
        trigger=trigger,
        task_id=None if n % 2 else f"task-{n}",
        skipped=bool(n % 2),
        reason="overlap" if n % 2 else "",
    )


def test_save_get_round_trip(tmp_path: Path) -> None:
    store = ScheduleStore(tmp_path)
    assert (tmp_path / "schedules").exists() is False
    store.save(_schedule())
    assert (tmp_path / "schedules").is_dir()
    assert store.get("sch-abc123") == _schedule()


def test_get_missing_returns_none(tmp_path: Path) -> None:
    assert ScheduleStore(tmp_path).get("sch-nope") is None


def test_list_sorted_by_name_then_id(tmp_path: Path) -> None:
    store = ScheduleStore(tmp_path)
    store.save(_schedule("sch-000002", "zebra"))
    store.save(_schedule("sch-000003", "apple"))
    store.save(_schedule("sch-000001", "apple"))
    assert [(item.name, item.id) for item in store.list()] == [
        ("apple", "sch-000001"),
        ("apple", "sch-000003"),
        ("zebra", "sch-000002"),
    ]


def test_list_skips_unreadable_files(tmp_path: Path) -> None:
    store = ScheduleStore(tmp_path)
    store.save(_schedule())
    (tmp_path / "schedules" / "sch-broken.json").write_text("not json", encoding="utf-8")
    assert [item.id for item in store.list()] == ["sch-abc123"]


def test_delete_removes_definition_and_runs(tmp_path: Path) -> None:
    store = ScheduleStore(tmp_path)
    store.save(_schedule())
    store.append_run(_run())
    assert store.delete("sch-abc123") is True
    assert store.get("sch-abc123") is None
    assert store.runs("sch-abc123") == []
    assert store.delete("sch-abc123") is False


def test_runs_newest_first(tmp_path: Path) -> None:
    store = ScheduleStore(tmp_path)
    for n in (1, 2, 3):
        store.append_run(_run(n=n))
    assert [run.n for run in store.runs("sch-abc123")] == [3, 2, 1]
    assert [run.n for run in store.runs("sch-abc123", limit=2)] == [3, 2]


def test_last_run_with_trigger_filter(tmp_path: Path) -> None:
    store = ScheduleStore(tmp_path)
    store.append_run(_run(n=1, trigger=Trigger.cron))
    store.append_run(_run(n=2, trigger=Trigger.manual))
    assert store.last_run("sch-abc123") is not None
    assert store.last_run("sch-abc123").n == 2  # type: ignore[union-attr]
    assert store.last_run("sch-abc123", Trigger.cron) is not None
    assert store.last_run("sch-abc123", Trigger.cron).n == 1  # type: ignore[union-attr]
    assert store.last_run("sch-missing") is None


def test_run_count(tmp_path: Path) -> None:
    store = ScheduleStore(tmp_path)
    assert store.run_count("sch-abc123") == 0
    store.append_run(_run(n=1))
    store.append_run(_run(n=2))
    assert store.run_count("sch-abc123") == 2


def test_id_validation_rejects_traversal(tmp_path: Path) -> None:
    store = ScheduleStore(tmp_path)
    with pytest.raises(ValueError, match="schedule id"):
        store.get("../x")
    with pytest.raises(ValueError, match="schedule id"):
        store.delete("../../etc")
    with pytest.raises(ValueError, match="schedule id"):
        store.runs("SCH-UPPER")
    with pytest.raises(ValueError, match="schedule id"):
        store.save(_schedule(schedule_id="ok"))
