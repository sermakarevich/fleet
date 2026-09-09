"""Event-trigger records: the data model for starting a task on a signal.

Called by `store.py` (persistence) and, later, the trigger supervisor tick,
the serve API, and the CLI. See ADR 0011 for the design (Source → Trigger
→ Firing). This module is pure data: no I/O, no imports beyond stdlib.
"""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

#: Trigger ids look like schedule ids: lowercase, dashes, 3-40 chars.
TRIGGER_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,39}$")

#: Allowed isolation values for a trigger template.
_ISOLATIONS = (None, "worktree", "none")

#: Keys `Trigger.from_dict` accepts; anything else is rejected.
_KNOWN_KEYS = frozenset(
    {
        "id",
        "name",
        "source",
        "title",
        "description",
        "source_params",
        "enabled",
        "target",
        "cwd",
        "coder",
        "model",
        "priority",
        "isolation",
        "labels",
        "max_open",
        "cooldown_sec",
        "created_at",
        "updated_at",
    }
)


class TargetKind(StrEnum):
    """What a trigger opens when it fires: one bead (workflow is a follow-up)."""

    task = "task"


@dataclass(frozen=True, slots=True)
class Trigger:
    """One saved event-trigger definition: which source, what task to open."""

    id: str
    name: str
    source: str
    title: str
    description: str = ""
    source_params: dict[str, str] = field(default_factory=dict)
    enabled: bool = True
    target: TargetKind = TargetKind.task
    cwd: str | None = None
    coder: str | None = None
    model: str | None = None
    priority: int = 2
    isolation: str | None = None
    labels: tuple[str, ...] = ()
    max_open: int = 2
    cooldown_sec: int = 0
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Return this trigger as plain JSON-safe data."""
        return {
            "id": self.id,
            "name": self.name,
            "source": self.source,
            "title": self.title,
            "description": self.description,
            "source_params": dict(self.source_params),
            "enabled": self.enabled,
            "target": self.target.value,
            "cwd": self.cwd,
            "coder": self.coder,
            "model": self.model,
            "priority": self.priority,
            "isolation": self.isolation,
            "labels": list(self.labels),
            "max_open": self.max_open,
            "cooldown_sec": self.cooldown_sec,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Trigger:
        """Build a trigger from stored data, rejecting unknown keys."""
        unknown = sorted(set(data) - _KNOWN_KEYS)
        if unknown:
            raise ValueError(f"unknown keys: {', '.join(unknown)}")
        trigger_id = data.get("id", "")
        if not isinstance(trigger_id, str) or not TRIGGER_ID_RE.match(trigger_id):
            raise ValueError(f"id: invalid {trigger_id!r}")
        for key in ("name", "source", "title"):
            value = data.get(key, "")
            if not isinstance(value, str) or not value:
                raise ValueError(f"{key}: required and must not be empty")
        try:
            target = TargetKind(data.get("target", "task"))
        except ValueError:
            raise ValueError(f"target: unknown target {data.get('target')!r}") from None
        priority = data.get("priority", 2)
        if isinstance(priority, bool) or not isinstance(priority, int):
            raise ValueError(f"priority: must be an int 0..4, got {priority!r}")
        if priority not in (0, 1, 2, 3, 4):
            raise ValueError(f"priority: must be an int 0..4, got {priority!r}")
        isolation = data.get("isolation")
        if isolation not in _ISOLATIONS:
            raise ValueError(f"isolation: must be one of worktree, none, got {isolation!r}")
        max_open = data.get("max_open", 2)
        if isinstance(max_open, bool) or not isinstance(max_open, int) or max_open < 0:
            raise ValueError(f"max_open: must be >= 0, got {max_open!r}")
        cooldown = data.get("cooldown_sec", 0)
        if isinstance(cooldown, bool) or not isinstance(cooldown, int) or cooldown < 0:
            raise ValueError(f"cooldown_sec: must be >= 0, got {cooldown!r}")
        params = _params_from_data(data.get("source_params"))
        labels = _labels_from_data(data.get("labels"))
        return cls(
            id=str(data["id"]),
            name=str(data["name"]),
            source=str(data["source"]),
            title=str(data["title"]),
            description=str(data.get("description", "")),
            source_params=params,
            enabled=bool(data.get("enabled", True)),
            target=target,
            cwd=data.get("cwd"),
            coder=data.get("coder"),
            model=data.get("model"),
            priority=priority,
            isolation=isolation,
            labels=labels,
            max_open=max_open,
            cooldown_sec=cooldown,
            created_at=str(data.get("created_at", "")),
            updated_at=str(data.get("updated_at", "")),
        )


def _params_from_data(raw: Any) -> dict[str, str]:
    """Source params map; absent means none, non-string values are an error."""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError("source_params: must be a mapping of names to values")
    for key, value in raw.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise ValueError("source_params: values must be strings")
    return dict(raw)


def _labels_from_data(raw: Any) -> tuple[str, ...]:
    """Label list; absent means none, `trigger:` prefix is reserved."""
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ValueError("labels: must be a list of strings")
    for item in raw:
        if not isinstance(item, str):
            raise ValueError("labels: must be a list of strings")
        if item.startswith("trigger:"):
            raise ValueError(f"labels: reserved prefix 'trigger:' in {item!r}")
    return tuple(raw)


@dataclass(frozen=True, slots=True)
class TriggerEvent:
    """One thing that happened: a stable key plus a flat string payload."""

    source: str
    key: str
    occurred_at: str
    payload: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        """Return this event as plain JSON-safe data."""
        return {
            "source": self.source,
            "key": self.key,
            "occurred_at": self.occurred_at,
            "payload": dict(self.payload),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TriggerEvent:
        """Build an event from stored data."""
        payload = data.get("payload", {})
        if not isinstance(payload, dict):
            raise ValueError("payload: must be a mapping of names to values")
        for key, value in payload.items():
            if not isinstance(key, str) or not isinstance(value, str):
                raise ValueError("payload: values must be strings")
        return cls(
            source=str(data.get("source", "")),
            key=str(data.get("key", "")),
            occurred_at=str(data.get("occurred_at", "")),
            payload=dict(payload),
        )


@dataclass(frozen=True, slots=True)
class Firing:
    """One trigger reacting to one event by opening one bead."""

    trigger_id: str
    n: int
    event_key: str
    fired_at: str
    task_id: str | None
    skipped: bool = False
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Return this firing as plain JSON-safe data."""
        return {
            "trigger_id": self.trigger_id,
            "n": self.n,
            "event_key": self.event_key,
            "fired_at": self.fired_at,
            "task_id": self.task_id,
            "skipped": self.skipped,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Firing:
        """Build a firing from stored data."""
        return cls(
            trigger_id=str(data.get("trigger_id", "")),
            n=int(data.get("n", 0)),
            event_key=str(data.get("event_key", "")),
            fired_at=str(data.get("fired_at", "")),
            task_id=data.get("task_id"),
            skipped=bool(data.get("skipped", False)),
            reason=str(data.get("reason", "")),
        )


def new_id() -> str:
    """Return a fresh trigger id: `trg-` plus 6 lowercase hex chars."""
    return "trg-" + secrets.token_hex(3)
