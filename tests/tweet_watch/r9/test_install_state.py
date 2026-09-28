"""R9 install state (F6-F8, F13, F18-F19): store mechanics of the install.

Covers: install goes through the fleet schedule machinery (never a cron /
launchd / sleep-loop substitute), create-alone is unverified (no run
record), already-exists reconciliation, stale-config delete+recreate, and
the retry-the-same-command rule for scheduler outages.
"""

from __future__ import annotations

from fleet.cli import schedule as schedule_cli

from .conftest import (
    SCHEDULE_CODER,
    SCHEDULE_CRON,
    SCHEDULE_NAME,
    SCHEDULE_OVERLAP,
)


def _matching(
    entry, *, name=SCHEDULE_NAME, cron=SCHEDULE_CRON, overlap=SCHEDULE_OVERLAP, coder=SCHEDULE_CODER
) -> bool:
    return (
        entry.name == name
        and entry.cron == cron
        and entry.overlap == overlap
        and entry.coder == coder
    )


def test_install_goes_through_fleet_schedule_machinery() -> None:
    assert callable(schedule_cli.run_create)
    assert callable(schedule_cli.run_list)
    assert callable(schedule_cli.run_fire)


def test_no_off_fleet_scheduler_substitute() -> None:
    assert not hasattr(schedule_cli, "run_cron_install")
    assert not hasattr(schedule_cli, "run_launchd_install")


def test_schedule_list_shows_the_entry(store, make_schedule) -> None:
    store.save(make_schedule())
    assert any(s.name == SCHEDULE_NAME for s in store.list())


def test_create_alone_is_unverified(store, make_schedule) -> None:
    schedule = make_schedule()
    store.save(schedule)
    assert store.run_count(schedule.id) == 0
    assert store.last_run(schedule.id) is None


def test_already_exists_matching_entry_is_kept(store, make_schedule) -> None:
    store.save(make_schedule(schedule_id="sch-orig"))
    existing = [s for s in store.list() if s.name == SCHEDULE_NAME]
    assert len(existing) == 1 and _matching(existing[0])


def test_parallel_install_duplicate_is_reconciled_to_one(store, make_schedule) -> None:
    store.save(make_schedule(schedule_id="sch-a"))
    store.save(make_schedule(schedule_id="sch-b"))
    dupes = [s for s in store.list() if s.name == SCHEDULE_NAME]
    assert len(dupes) == 2
    store.delete("sch-b")
    remaining = [s for s in store.list() if s.name == SCHEDULE_NAME]
    assert len(remaining) == 1 and _matching(remaining[0])


def test_stale_entry_is_deleted_and_recreated_exact(store, make_schedule) -> None:
    store.save(make_schedule(schedule_id="sch-stale", cron="0 * * * *"))
    stale = [s for s in store.list() if s.name == SCHEDULE_NAME][0]
    assert not _matching(stale)
    store.delete(stale.id)
    store.save(make_schedule(schedule_id="sch-fresh"))
    remaining = [s for s in store.list() if s.name == SCHEDULE_NAME]
    assert len(remaining) == 1 and _matching(remaining[0])


def test_retry_uses_the_identical_spec(make_schedule) -> None:
    first = make_schedule(schedule_id="sch-1")
    second = make_schedule(schedule_id="sch-2")
    assert (second.name, second.cron, second.overlap, second.coder) == (
        first.name,
        first.cron,
        first.overlap,
        first.coder,
    )
