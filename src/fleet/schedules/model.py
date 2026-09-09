"""Schedule and run records: the data model for recurring workers.

Called by `store.py` (persistence) and, later, the scheduler service, the
serve API, and the CLI. Template placeholders (`{name}`, `{date}`, `{time}`,
`{n}`) are rendered per run; unknown `{placeholders}` pass through untouched.
"""

from __future__ import annotations

import secrets
import string
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fleet.schedules.cron import CronError, parse


class OverlapPolicy(StrEnum):
    """What a schedule does when the previous run's task is still open."""

    skip = "skip"
    queue = "queue"


class Trigger(StrEnum):
    """How a run was fired: by the cron tick or by hand."""

    cron = "cron"
    manual = "manual"


class TargetKind(StrEnum):
    """What a schedule opens when due: one bead, or one workflow run."""

    task = "task"
    workflow = "workflow"


@dataclass(frozen=True, slots=True)
class Schedule:
    """One saved recurring-worker template plus its cron expression."""

    id: str
    name: str
    cron: str
    timezone: str = "UTC"
    enabled: bool = True
    title: str = ""
    description: str = ""
    cwd: str | None = None
    coder: str | None = None
    model: str | None = None
    priority: int = 2
    overlap: OverlapPolicy = OverlapPolicy.skip
    target: TargetKind = TargetKind.task
    workflow_id: str | None = None
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Return this schedule as plain JSON-safe data."""
        return {
            "id": self.id,
            "name": self.name,
            "cron": self.cron,
            "timezone": self.timezone,
            "enabled": self.enabled,
            "title": self.title,
            "description": self.description,
            "cwd": self.cwd,
            "coder": self.coder,
            "model": self.model,
            "priority": self.priority,
            "overlap": self.overlap.value,
            "target": self.target.value,
            "workflow_id": self.workflow_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Schedule:
        """Build a schedule from stored data, ignoring unknown keys."""
        try:
            overlap = OverlapPolicy(data.get("overlap", "skip"))
        except ValueError:
            raise ValueError(f"overlap: unknown policy {data.get('overlap')!r}") from None
        cron = str(data.get("cron", ""))
        try:
            parse(cron)
        except CronError as exc:
            raise CronError(str(exc)) from None
        timezone = str(data.get("timezone", "UTC"))
        try:
            ZoneInfo(timezone)
        except ZoneInfoNotFoundError:
            raise CronError(f"timezone: unknown zone {timezone!r}") from None
        for key in ("id", "name", "created_at", "updated_at"):
            if not data.get(key):
                raise ValueError(f"{key}: required and must not be empty")
        try:
            target = TargetKind(data.get("target", "task"))
        except ValueError:
            raise ValueError(f"target: unknown target {data.get('target')!r}") from None
        workflow_id = data.get("workflow_id")
        if target is TargetKind.workflow and not workflow_id:
            raise ValueError("workflow_id: required when target is workflow")
        if target is TargetKind.task and not data.get("title"):
            raise ValueError("title: required and must not be empty")
        return cls(
            id=str(data["id"]),
            name=str(data["name"]),
            cron=cron,
            timezone=timezone,
            enabled=bool(data.get("enabled", True)),
            title=str(data.get("title", "")),
            description=str(data.get("description", "")),
            cwd=data.get("cwd"),
            coder=data.get("coder"),
            model=data.get("model"),
            priority=int(data.get("priority", 2)),
            overlap=overlap,
            target=target,
            workflow_id=str(workflow_id) if workflow_id is not None else None,
            created_at=str(data["created_at"]),
            updated_at=str(data["updated_at"]),
        )


@dataclass(frozen=True, slots=True)
class ScheduleRun:
    """One firing of a schedule: when due, when fired, and what it opened."""

    schedule_id: str
    n: int
    scheduled_for: str
    fired_at: str
    trigger: Trigger
    task_id: str | None
    skipped: bool
    reason: str = ""
    workflow_run_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return this run as plain JSON-safe data."""
        return {
            "schedule_id": self.schedule_id,
            "n": self.n,
            "scheduled_for": self.scheduled_for,
            "fired_at": self.fired_at,
            "trigger": self.trigger.value,
            "task_id": self.task_id,
            "skipped": self.skipped,
            "reason": self.reason,
            "workflow_run_id": self.workflow_run_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ScheduleRun:
        """Build a run from stored data, ignoring unknown keys."""
        raw = data.get("trigger")
        if not isinstance(raw, str):
            raise ValueError(f"trigger: unknown trigger {raw!r}")
        try:
            trigger = Trigger(raw)
        except ValueError:
            raise ValueError(f"trigger: unknown trigger {raw!r}") from None
        return cls(
            schedule_id=str(data.get("schedule_id", "")),
            n=int(data.get("n", 0)),
            scheduled_for=str(data.get("scheduled_for", "")),
            fired_at=str(data.get("fired_at", "")),
            trigger=trigger,
            task_id=data.get("task_id"),
            skipped=bool(data.get("skipped", False)),
            reason=str(data.get("reason", "")),
            workflow_run_id=data.get("workflow_run_id"),
        )


def new_id() -> str:
    """Return a fresh schedule id: `sch-` plus 6 lowercase hex chars."""
    return "sch-" + secrets.token_hex(3)


class _LenientMapping(dict):
    """Format mapping that leaves unknown `{placeholders}` untouched."""

    def __missing__(self, key: str) -> str:
        """Return the placeholder unchanged when no value exists."""
        return "{" + key + "}"


def render(template: str, schedule: Schedule, run_n: int, when: datetime) -> str:
    """Fill `{name}`, `{date}`, `{time}`, `{n}` in a task template."""
    moment = when if when.tzinfo is not None else when.replace(tzinfo=UTC)
    try:
        local = moment.astimezone(ZoneInfo(schedule.timezone))
    except ZoneInfoNotFoundError:
        local = moment.astimezone(UTC)
    values = _LenientMapping(
        {
            "name": schedule.name,
            "date": local.strftime("%Y-%m-%d"),
            "time": local.strftime("%H:%M"),
            "n": run_n,
        }
    )
    try:
        return string.Formatter().vformat(template, (), values)
    except ValueError:
        return template
