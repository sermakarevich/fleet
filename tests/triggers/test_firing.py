"""Tests for trigger firing: `decide`, `fire`, and the `fire_due` tick loop."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar

import pytest

from fleet.beads.client import BdError
from fleet.core.task import Task
from fleet.triggers.firing import decide, fire, fire_due, open_count
from fleet.triggers.model import Trigger, TriggerEvent
from fleet.triggers.sources import SOURCES
from fleet.triggers.store import TriggerStore
from tests.conftest import FakeQueue, _metadata_of

NOW = datetime(2026, 9, 9, 12, 0, 0, tzinfo=UTC)


class FakeLog:
    """Test double that records every log call by level and event name."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict]] = []

    def _record(self, level: str, event: str, kw: dict) -> None:
        self.calls.append((level, event, kw))

    def debug(self, event: str, **kw: Any) -> None:
        """Record a debug call."""
        self._record("debug", event, kw)

    def info(self, event: str, **kw: Any) -> None:
        """Record an info call."""
        self._record("info", event, kw)

    def warning(self, event: str, **kw: Any) -> None:
        """Record a warning call."""
        self._record("warning", event, kw)

    def error(self, event: str, **kw: Any) -> None:
        """Record an error call."""
        self._record("error", event, kw)

    def events(self, level: str, name: str) -> list[dict]:
        """Calls matching a level and event name."""
        return [kw for lv, ev, kw in self.calls if lv == level and ev == name]


def _trigger(**overrides: Any) -> Trigger:
    """One enabled trigger on the `blocked_task` source unless overridden."""
    data: dict[str, Any] = {
        "id": "trg-abc123",
        "name": "watcher",
        "source": "blocked_task",
        "title": "Investigate {{event.task_id}}",
        "description": "stuck: {{event.title}}",
    }
    data.update(overrides)
    return Trigger.from_dict(data)


def _event(key: str = "task-1@2026-09-09T11:00:00+00:00", **payload: str) -> TriggerEvent:
    """One event with a task payload unless overridden."""
    full = {"task_id": "task-1", "title": "stuck"}
    full.update(payload)
    return TriggerEvent(
        source="blocked_task",
        key=key,
        occurred_at="2026-09-09T11:00:00+00:00",
        payload=full,
    )


def test_decide_table() -> None:
    """Every decide branch fires in order: disabled, fired, max_open, cooldown, open."""
    base = _trigger()
    cases = [
        ("disabled skips", _trigger(enabled=False), False, 0, None, "skip", "disabled"),
        ("already fired skips", base, True, 0, None, "skip", "already fired for k"),
        ("max_open reached skips", base, False, 2, None, "skip", "max_open 2 reached"),
        (
            "cooldown skips",
            _trigger(cooldown_sec=3600),
            False,
            0,
            datetime(2026, 9, 9, 11, 30, tzinfo=UTC),
            "skip",
            "cooldown until 2026-09-09T12:30:00+00:00",
        ),
        (
            "expired cooldown opens",
            _trigger(cooldown_sec=3600),
            False,
            0,
            datetime(2026, 9, 9, 10, 0, tzinfo=UTC),
            "open",
            "",
        ),
        ("fresh event opens", base, False, 0, None, "open", ""),
        (
            "zero max_open always skips",
            _trigger(max_open=0),
            False,
            0,
            None,
            "skip",
            "max_open 0 reached",
        ),
    ]
    for label, trigger, fired, count, last, want_action, want_reason in cases:
        event = _event(key="k")
        got = decide(
            trigger,
            event,
            already_fired=fired,
            open_count=count,
            last_fired_at=last,
            now=NOW,
        )
        assert (got.action, got.reason) == (want_action, want_reason), label


def test_fire_opens_task_and_appends_row(tmp_path: Path) -> None:
    """Fire renders the template, records metadata, and appends n=1 then n=2."""
    store = TriggerStore(tmp_path)
    queue = FakeQueue()
    trigger = _trigger(labels=["team:a"])
    store.save(trigger)

    first = fire(trigger, _event(key="k1"), store=store, queue=queue, now=NOW, fleet_home=tmp_path)
    assert first.n == 1
    assert first.task_id is not None
    assert first.skipped is False

    created = queue.created[0]
    assert created["title"] == "Investigate task-1"
    assert created["description"] == "stuck: stuck"
    assert "-l trigger:trg-abc123" in (created["extra_args"] or "")
    meta = _metadata_of(created["extra_args"])
    assert meta["fleet_trigger_id"] == "trg-abc123"
    assert meta["fleet_trigger_event"] == "k1"
    assert meta["fleet_trigger_n"] == 1

    second = fire(trigger, _event(key="k2"), store=store, queue=queue, now=NOW, fleet_home=tmp_path)
    assert second.n == 2
    assert [f.n for f in store.firings(trigger.id)] == [2, 1]


def test_fire_metadata_has_rendered_cwd(tmp_path: Path) -> None:
    """`fleet_cwd` in the bead metadata is the rendered path, never the raw template."""
    store = TriggerStore(tmp_path)
    queue = FakeQueue()
    trigger = _trigger(cwd="/repo/{{event.task_id}}")
    store.save(trigger)

    firing = fire(trigger, _event(key="k1"), store=store, queue=queue, now=NOW, fleet_home=tmp_path)
    created = queue.created[0]
    meta = _metadata_of(created["extra_args"])
    assert meta["fleet_cwd"] == "/repo/task-1"
    assert "{{" not in meta["fleet_cwd"]
    assert created["cwd"] == "/repo/task-1"
    _ = firing


def test_decide_skips_when_cwd_renders_empty() -> None:
    """A cwd template is set but renders empty (or unresolved) -> skip, no bead."""
    trigger = _trigger(cwd="{{event.cwd}}")
    event = _event(key="k")
    got = decide(
        trigger,
        event,
        already_fired=False,
        open_count=0,
        last_fired_at=None,
        now=NOW,
        rendered_cwd="",
    )
    assert (got.action, got.reason) == ("skip", "cwd template rendered empty")

    got_unresolved = decide(
        trigger,
        event,
        already_fired=False,
        open_count=0,
        last_fired_at=None,
        now=NOW,
        rendered_cwd="{{event.cwd}}",
    )
    assert (got_unresolved.action, got_unresolved.reason) == ("skip", "cwd template rendered empty")


def test_decide_cwd_not_applicable_when_no_template() -> None:
    """A trigger with no cwd template still fires (the rule does not apply)."""
    trigger = _trigger()
    event = _event(key="k")
    got = decide(
        trigger,
        event,
        already_fired=False,
        open_count=0,
        last_fired_at=None,
        now=NOW,
        rendered_cwd=None,
    )
    assert got.action == "open"


def test_fire_due_skips_empty_cwd_and_logs_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An event whose payload lacks `cwd` renders the template empty; no bead opens."""
    monkeypatch.setitem(SOURCES, "fake_src", _FakeSource)
    _FakeSource.queued = [_event(key="k1", cwd="")]
    store = TriggerStore(tmp_path)
    store.save(_trigger(source="fake_src", cwd="{{event.cwd}}"))
    queue = FakeQueue()
    log = FakeLog()

    fired = fire_due(store=store, queue=queue, fleet_home=tmp_path, now=NOW, log=log)
    assert fired == []
    assert queue.created == []
    assert store.firings("trg-abc123") == []
    warnings = log.events("warning", "trigger_skipped")
    assert len(warnings) == 1
    assert warnings[0]["reason"] == "cwd template rendered empty"


def test_fire_isolation_sets_overrides(tmp_path: Path) -> None:
    """An isolated trigger persists its isolation through set_overrides."""

    class SpyQueue(FakeQueue):
        def __init__(self) -> None:
            super().__init__()
            self.overrides: list[dict] = []

        def set_overrides(self, task_id: str, **kw: Any) -> None:
            self.overrides.append({"id": task_id, **kw})
            super().set_overrides(task_id, **kw)

    store = TriggerStore(tmp_path)
    queue = SpyQueue()
    firing = fire(
        _trigger(isolation="worktree"),
        _event(),
        store=store,
        queue=queue,
        now=NOW,
        fleet_home=tmp_path,
    )
    assert queue.overrides == [
        {
            "id": firing.task_id,
            "coder": None,
            "model": None,
            "worker": None,
            "isolation": "worktree",
            "job_gate": None,
        }
    ]


def test_fire_bd_error_recorded_as_skipped(tmp_path: Path) -> None:
    """A `bd` failure appends a skipped firing row, then re-raises."""

    class BadQueue(FakeQueue):
        def create_task(self, *args: Any, **kw: Any) -> Task:
            raise BdError("bd down")

    store = TriggerStore(tmp_path)
    with pytest.raises(BdError):
        fire(_trigger(), _event(), store=store, queue=BadQueue(), now=NOW, fleet_home=tmp_path)
    rows = store.firings("trg-abc123")
    assert len(rows) == 1
    assert rows[0].skipped is True
    assert rows[0].task_id is None
    assert rows[0].reason.startswith("bd error:")


def test_open_count_ignores_closed(tmp_path: Path) -> None:
    """Closed beads no longer count against max_open; errors mean 0."""
    _ = tmp_path
    trigger = _trigger()
    queue = FakeQueue()
    assert open_count(trigger, queue) == 0
    t1 = queue.create_task(
        "a", extra_args='-p 2 -l x --metadata \'{"fleet_trigger_id": "trg-abc123"}\''
    )
    queue.create_task("b")
    assert open_count(trigger, queue) == 1
    queue.close(t1.id)
    assert open_count(trigger, queue) == 0

    class BadQueue(FakeQueue):
        def list_by_metadata(self, field: str, value: str) -> list:
            raise RuntimeError("boom")

    assert open_count(trigger, BadQueue()) == 0


class _FakeSource:
    """Test source returning whatever events the test queued."""

    kind: ClassVar[str] = "fake_src"
    queued: ClassVar[list[TriggerEvent]] = []

    def poll(self, ctx: Any) -> list[TriggerEvent]:
        """Return the queued events."""
        _ = ctx
        return list(type(self).queued)


def test_fire_due_opens_once_per_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Each event key opens one bead; a second tick re-opens nothing."""
    monkeypatch.setitem(SOURCES, "fake_src", _FakeSource)
    _FakeSource.queued = [_event(key="k1"), _event(key="k2")]
    store = TriggerStore(tmp_path)
    store.save(_trigger(source="fake_src"))
    queue = FakeQueue()
    log = FakeLog()

    first = fire_due(store=store, queue=queue, fleet_home=tmp_path, now=NOW, log=log)
    assert len(first) == 2
    assert len(queue.created) == 2
    assert len(log.events("info", "trigger_fired")) == 2

    second = fire_due(store=store, queue=queue, fleet_home=tmp_path, now=NOW, log=log)
    assert second == []
    assert len(queue.created) == 2


def test_fire_due_max_open_and_disabled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Max_open caps new beads; disabled triggers are never polled."""
    monkeypatch.setitem(SOURCES, "fake_src", _FakeSource)
    _FakeSource.queued = [_event(key="k1"), _event(key="k2"), _event(key="k3")]
    store = TriggerStore(tmp_path)
    store.save(_trigger(id="trg-capped", source="fake_src", max_open=1))
    store.save(_trigger(id="trg-off", source="fake_src", enabled=False))
    queue = FakeQueue()
    log = FakeLog()

    fired = fire_due(store=store, queue=queue, fleet_home=tmp_path, now=NOW, log=log)
    assert [f.trigger_id for f in fired] == ["trg-capped"]
    assert len(queue.created) == 1
    assert log.events("debug", "trigger_skipped")


def test_fire_due_unknown_source_logged(tmp_path: Path) -> None:
    """An unknown source kind logs a warning instead of raising."""
    store = TriggerStore(tmp_path)
    store.save(_trigger(source="nope"))
    log = FakeLog()
    assert fire_due(store=store, queue=FakeQueue(), fleet_home=tmp_path, now=NOW, log=log) == []
    assert len(log.events("warning", "trigger_source_unknown")) == 1


def test_fire_due_bd_error_continues(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """One trigger's `bd` failure is logged; the next trigger still fires."""
    monkeypatch.setitem(SOURCES, "fake_src", _FakeSource)
    _FakeSource.queued = [_event(key="k1")]
    store = TriggerStore(tmp_path)
    store.save(_trigger(id="trg-bad", source="fake_src"))
    store.save(_trigger(id="trg-good", source="fake_src"))

    class FlakyQueue(FakeQueue):
        def __init__(self) -> None:
            super().__init__()
            self.calls = 0

        def create_task(self, title: str, *args: Any, **kw: Any) -> Task:
            self.calls += 1
            if self.calls == 1:
                raise BdError("bd down")
            return super().create_task(title, *args, **kw)

    log = FakeLog()
    fired = fire_due(store=store, queue=FlakyQueue(), fleet_home=tmp_path, now=NOW, log=log)
    assert [f.trigger_id for f in fired] == ["trg-good"]
    assert len(log.events("error", "trigger_fire_failed")) == 1
    assert store.firings("trg-bad")[0].skipped is True
