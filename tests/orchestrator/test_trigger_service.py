"""Tests for orchestrator/triggers.py: the tick that fires enabled triggers."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, ClassVar

import pytest

from fleet.core.clock import FakeClock
from fleet.core.limits import TRIGGER_TICK_SEC
from fleet.orchestrator import default_services
from fleet.orchestrator.service import ServiceOrder
from fleet.orchestrator.triggers import make_trigger_service, trigger_tick
from fleet.triggers.model import Trigger, TriggerEvent
from fleet.triggers.sources import SOURCES
from fleet.triggers.store import TriggerStore
from tests.conftest import FakeQueue, make_supervisor

NOW = datetime(2026, 9, 9, 12, 0, 0, tzinfo=UTC)


class _FakeSource:
    """Test source returning whatever events the test queued."""

    kind: ClassVar[str] = "fake_src"
    queued: ClassVar[list[TriggerEvent]] = []

    def poll(self, ctx: Any) -> list[TriggerEvent]:
        """Return the queued events."""
        _ = ctx
        return list(type(self).queued)


def _event(key: str = "evt-1") -> TriggerEvent:
    """One event with a small payload."""
    return TriggerEvent(
        source="fake_src",
        key=key,
        occurred_at="2026-09-09T11:00:00+00:00",
        payload={"task_id": "task-1", "title": "stuck"},
    )


def _trigger(**overrides: Any) -> Trigger:
    """One enabled trigger on the fake source unless overridden."""
    data: dict[str, Any] = {
        "id": "trg-abc123",
        "name": "watcher",
        "source": "fake_src",
        "title": "Investigate {{event.task_id}}",
        "description": "stuck: {{event.title}}",
    }
    data.update(overrides)
    return Trigger.from_dict(data)


def _state(tmp_path: Path, **overrides: Any):
    """Supervisor state over tmp_path with a FakeQueue and a FakeClock at NOW."""
    queue = FakeQueue()
    sup = make_supervisor(tmp_path, queue=queue, services=[], checks=[])
    st = sup.state
    st.clock = FakeClock(start=NOW)
    TriggerStore(tmp_path).save(_trigger(**overrides))
    return st, queue


def test_tick_fires_one_task_and_records_firing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An enabled trigger with one event opens one bead and one firing row."""
    monkeypatch.setitem(SOURCES, "fake_src", _FakeSource)
    _FakeSource.queued = [_event()]
    st, queue = _state(tmp_path)

    asyncio.run(trigger_tick(st))

    assert len(queue._tasks) == 1
    assert len(TriggerStore(tmp_path).firings("trg-abc123")) == 1


def test_second_tick_creates_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The same event key fires once; a repeat tick is a no-op."""
    monkeypatch.setitem(SOURCES, "fake_src", _FakeSource)
    _FakeSource.queued = [_event()]
    st, queue = _state(tmp_path)

    asyncio.run(trigger_tick(st))
    asyncio.run(trigger_tick(st))

    assert len(queue._tasks) == 1
    assert len(TriggerStore(tmp_path).firings("trg-abc123")) == 1


def test_paused_supervisor_creates_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A future paused_until skips the tick entirely (no task, no firing)."""
    monkeypatch.setitem(SOURCES, "fake_src", _FakeSource)
    _FakeSource.queued = [_event()]
    st, queue = _state(tmp_path)
    st.paused_until = NOW + timedelta(minutes=5)

    asyncio.run(trigger_tick(st))

    assert len(queue._tasks) == 0
    assert TriggerStore(tmp_path).firings("trg-abc123") == []


def test_factory_defaults() -> None:
    """Default cadence is TRIGGER_TICK_SEC with Trigger order and tick hooks."""
    svc = make_trigger_service()
    assert svc.name == "triggers"
    assert svc.order == ServiceOrder.Trigger
    assert svc.interval_sec == TRIGGER_TICK_SEC
    assert svc.tick is trigger_tick
    assert svc.on_start is trigger_tick


def test_default_services_contains_triggers() -> None:
    """default_services() wires the triggers service."""
    names = [svc.name for svc in default_services()]
    assert "triggers" in names
