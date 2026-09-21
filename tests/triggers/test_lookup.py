"""Tests for `triggers.lookup` (blocked task -> investigation bead)."""

from __future__ import annotations

from pathlib import Path

from fleet.triggers.lookup import BLOCKED_TASK_SOURCE, event_key, investigation_task_id
from fleet.triggers.model import Firing, Trigger
from fleet.triggers.store import TriggerStore


def _save_trigger(store: TriggerStore, trigger_id: str, source: str) -> None:
    store.save(
        Trigger(
            id=trigger_id,
            name="test",
            source=source,
            title="Investigate",
        )
    )


def _fire(
    store: TriggerStore,
    trigger_id: str,
    event_key_: str,
    inv_id: str | None,
    n: int = 1,
    skipped: bool = False,
) -> None:
    store.append_firing(
        Firing(
            trigger_id=trigger_id,
            n=n,
            event_key=event_key_,
            fired_at="2026-09-09T00:01:00+00:00",
            task_id=inv_id,
            skipped=skipped,
            reason="",
        )
    )


def test_event_key_formatting() -> None:
    assert event_key("fleet-1", "2026-09-09T00:00:00+00:00") == (
        "fleet-1@2026-09-09T00:00:00+00:00"
    )
    assert event_key("fleet-1", None) == "fleet-1@unknown"
    assert event_key("fleet-1", "") == "fleet-1@unknown"


def test_investigation_hit(tmp_path: Path) -> None:
    store = TriggerStore(tmp_path)
    _save_trigger(store, "trg-blocked-one", BLOCKED_TASK_SOURCE)
    _fire(store, "trg-blocked-one", "fleet-1@ts-1", "inv-9")
    assert investigation_task_id(store, "fleet-1", "ts-1") == "inv-9"


def test_investigation_miss(tmp_path: Path) -> None:
    store = TriggerStore(tmp_path)
    _save_trigger(store, "trg-blocked-one", BLOCKED_TASK_SOURCE)
    _fire(store, "trg-blocked-one", "fleet-1@ts-1", "inv-9")
    assert investigation_task_id(store, "fleet-1", "other-ts") is None
    assert investigation_task_id(store, "fleet-2", "ts-1") is None


def test_investigation_ignores_skipped_firing(tmp_path: Path) -> None:
    store = TriggerStore(tmp_path)
    _save_trigger(store, "trg-blocked-one", BLOCKED_TASK_SOURCE)
    _fire(store, "trg-blocked-one", "fleet-1@ts-1", "inv-9", skipped=True)
    assert investigation_task_id(store, "fleet-1", "ts-1") is None


def test_investigation_ignores_other_sources(tmp_path: Path) -> None:
    store = TriggerStore(tmp_path)
    _save_trigger(store, "trg-schedule-one", "schedule")
    _fire(store, "trg-schedule-one", "fleet-1@ts-1", "inv-9")
    assert investigation_task_id(store, "fleet-1", "ts-1") is None
