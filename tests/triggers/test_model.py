"""Tests for `triggers.model` (records and validation)."""

from __future__ import annotations

from typing import Any

import pytest

from fleet.triggers.model import Firing, TargetKind, Trigger, TriggerEvent, new_id


def _trigger(**overrides: Any) -> Trigger:
    base: dict[str, Any] = {
        "id": "trg-abc123",
        "name": "investigate",
        "source": "blocked_task",
        "title": "Investigate {{event.task_id}}",
        "created_at": "2026-09-09T00:00:00+00:00",
        "updated_at": "2026-09-09T00:00:00+00:00",
    }
    base.update(overrides)
    return Trigger.from_dict(base)


def test_round_trip() -> None:
    trigger = _trigger(
        description="desc",
        source_params={"fleet_blocked_only": "true"},
        cwd="{{event.cwd}}",
        coder="opencode",
        model="m",
        priority=1,
        isolation="worktree",
        labels=["urgent"],
        max_open=3,
        cooldown_sec=60,
    )
    assert Trigger.from_dict(trigger.to_dict()) == trigger


def test_defaults() -> None:
    trigger = _trigger()
    assert trigger.description == ""
    assert trigger.source_params == {}
    assert trigger.enabled is True
    assert trigger.target == TargetKind.task
    assert trigger.priority == 2
    assert trigger.max_open == 2
    assert trigger.cooldown_sec == 0
    assert trigger.labels == ()


def test_bad_id_raises() -> None:
    with pytest.raises(ValueError, match="id"):
        _trigger(id="BAD")
    with pytest.raises(ValueError, match="id"):
        _trigger(id="../x")


def test_empty_name_source_title_raise() -> None:
    with pytest.raises(ValueError, match="name"):
        _trigger(name="")
    with pytest.raises(ValueError, match="source"):
        _trigger(source="")
    with pytest.raises(ValueError, match="title"):
        _trigger(title="")


def test_bad_priority_raises() -> None:
    with pytest.raises(ValueError, match="priority"):
        _trigger(priority=5)
    with pytest.raises(ValueError, match="priority"):
        _trigger(priority=-1)


def test_bad_isolation_raises() -> None:
    with pytest.raises(ValueError, match="isolation"):
        _trigger(isolation="docker")


def test_bad_max_open_raises() -> None:
    with pytest.raises(ValueError, match="max_open"):
        _trigger(max_open=-1)


def test_bad_cooldown_raises() -> None:
    with pytest.raises(ValueError, match="cooldown_sec"):
        _trigger(cooldown_sec=-5)


def test_non_string_source_params_raise() -> None:
    with pytest.raises(ValueError, match="source_params"):
        _trigger(source_params={"k": 3})


def test_reserved_label_prefix_raises() -> None:
    with pytest.raises(ValueError, match="labels"):
        _trigger(labels=["trigger:trg-abc123"])


def test_unknown_keys_raise() -> None:
    data = _trigger().to_dict()
    data["future_field"] = "whatever"
    with pytest.raises(ValueError, match="unknown keys"):
        Trigger.from_dict(data)


def test_bad_target_raises() -> None:
    data = _trigger().to_dict()
    data["target"] = "fleet"
    with pytest.raises(ValueError, match="target"):
        Trigger.from_dict(data)


def test_new_id_shape() -> None:
    first, second = new_id(), new_id()
    assert first.startswith("trg-") and len(first) == 10
    assert first != second
    body = first.removeprefix("trg-")
    assert all(char in "0123456789abcdef" for char in body)


def test_event_round_trip() -> None:
    event = TriggerEvent(
        source="blocked_task",
        key="fleet-abc@2026-09-09T00:00:00+00:00",
        occurred_at="2026-09-09T00:00:00+00:00",
        payload={"task_id": "fleet-abc"},
    )
    assert TriggerEvent.from_dict(event.to_dict()) == event


def test_firing_round_trip() -> None:
    firing = Firing(
        trigger_id="trg-abc123",
        n=2,
        event_key="fleet-abc@2026-09-09T00:00:00+00:00",
        fired_at="2026-09-09T00:01:00+00:00",
        task_id="fleet-xyz",
    )
    clone = Firing.from_dict(firing.to_dict())
    assert clone == firing
    assert clone.skipped is False
    assert clone.reason == ""
