"""Tests for `triggers.store` (definitions and firing history on disk)."""

from __future__ import annotations

from pathlib import Path

import pytest

from fleet.triggers.model import Firing, Trigger
from fleet.triggers.store import TriggerStore


def _trigger(trigger_id: str = "trg-abc123", name: str = "investigate") -> Trigger:
    return Trigger.from_dict(
        {
            "id": trigger_id,
            "name": name,
            "source": "blocked_task",
            "title": "Investigate {{event.task_id}}",
            "created_at": "2026-09-09T00:00:00+00:00",
            "updated_at": "2026-09-09T00:00:00+00:00",
        }
    )


def _firing(
    trigger_id: str = "trg-abc123",
    n: int = 1,
    event_key: str = "fleet-abc@2026-09-09T00:00:00+00:00",
    skipped: bool = False,
) -> Firing:
    return Firing(
        trigger_id=trigger_id,
        n=n,
        event_key=event_key,
        fired_at="2026-09-09T00:01:00+00:00",
        task_id=None if skipped else f"task-{n}",
        skipped=skipped,
        reason="already fired" if skipped else "",
    )


def test_save_get_round_trip(tmp_path: Path) -> None:
    store = TriggerStore(tmp_path)
    assert (tmp_path / "triggers").exists() is False
    store.save(_trigger())
    assert (tmp_path / "triggers").is_dir()
    assert store.get("trg-abc123") == _trigger()


def test_get_missing_returns_none(tmp_path: Path) -> None:
    assert TriggerStore(tmp_path).get("trg-nope") is None


def test_list_sorted_by_id(tmp_path: Path) -> None:
    store = TriggerStore(tmp_path)
    store.save(_trigger("trg-000002", "zebra"))
    store.save(_trigger("trg-000001", "zebra"))
    assert [item.id for item in store.list()] == ["trg-000001", "trg-000002"]


def test_list_skips_unreadable_files(tmp_path: Path) -> None:
    store = TriggerStore(tmp_path)
    store.save(_trigger())
    (tmp_path / "triggers" / "trg-broken.json").write_text("not json", encoding="utf-8")
    assert [item.id for item in store.list()] == ["trg-abc123"]


def test_delete_removes_definition_and_firings(tmp_path: Path) -> None:
    store = TriggerStore(tmp_path)
    store.save(_trigger())
    store.append_firing(_firing())
    assert store.delete("trg-abc123") is True
    assert store.get("trg-abc123") is None
    assert store.firings("trg-abc123") == []
    assert store.delete("trg-abc123") is False


def test_firings_newest_first(tmp_path: Path) -> None:
    store = TriggerStore(tmp_path)
    for n in (1, 2, 3):
        store.append_firing(_firing(n=n, event_key=f"key-{n}"))
    assert [firing.n for firing in store.firings("trg-abc123")] == [3, 2, 1]
    assert [firing.n for firing in store.firings("trg-abc123", limit=2)] == [3, 2]


def test_firing_count(tmp_path: Path) -> None:
    store = TriggerStore(tmp_path)
    assert store.firing_count("trg-abc123") == 0
    store.append_firing(_firing(n=1, event_key="key-1"))
    store.append_firing(_firing(n=2, event_key="key-2"))
    assert store.firing_count("trg-abc123") == 2


def test_has_fired_ignores_skipped(tmp_path: Path) -> None:
    store = TriggerStore(tmp_path)
    store.append_firing(_firing(n=1, event_key="key-1", skipped=True))
    assert store.has_fired("trg-abc123", "key-1") is False
    store.append_firing(_firing(n=2, event_key="key-1"))
    assert store.has_fired("trg-abc123", "key-1") is True
    assert store.has_fired("trg-abc123", "key-missing") is False


def test_firing_for_event_returns_newest_non_skipped(tmp_path: Path) -> None:
    store = TriggerStore(tmp_path)
    assert store.firing_for_event("trg-abc123", "key-1") is None
    store.append_firing(_firing(n=1, event_key="key-1", skipped=True))
    assert store.firing_for_event("trg-abc123", "key-1") is None
    store.append_firing(_firing(n=2, event_key="key-1"))
    store.append_firing(_firing(n=3, event_key="key-1"))
    found = store.firing_for_event("trg-abc123", "key-1")
    assert found is not None
    assert found.n == 3
    assert store.firing_for_event("trg-abc123", "key-missing") is None


def test_last_firing_ignores_skipped(tmp_path: Path) -> None:
    store = TriggerStore(tmp_path)
    assert store.last_firing("trg-abc123") is None
    store.append_firing(_firing(n=1, event_key="key-1"))
    store.append_firing(_firing(n=2, event_key="key-2", skipped=True))
    last = store.last_firing("trg-abc123")
    assert last is not None
    assert last.n == 1


def test_id_validation_rejects_traversal(tmp_path: Path) -> None:
    store = TriggerStore(tmp_path)
    with pytest.raises(ValueError, match="trigger id"):
        store.get("../x")
    with pytest.raises(ValueError, match="trigger id"):
        store.delete("../../etc")
    with pytest.raises(ValueError, match="trigger id"):
        store.firings("TRG-UPPER")
    with pytest.raises(ValueError, match="trigger id"):
        store.save(Trigger(id="ok", name="x", source="blocked_task", title="t"))
