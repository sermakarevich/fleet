"""Workflow data model: saved definitions, runs, and the stage/needs rules.

Called by `store.py` and `yaml_io.py` (persistence) and, later, the run
engine, the serve API, and the CLI. A workflow is a saved definition of
workers arranged in stages; a run is one execution of it. Validation is
pure: `validate` returns human-readable problems, `ensure_valid` raises.
"""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Any

from fleet.core.errors import WorkflowInvalid

_STEP_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")

_PRIORITY_MIN = 0
_PRIORITY_MAX = 4

_BASE36 = "0123456789abcdefghijklmnopqrstuvwxyz"


class Trigger(StrEnum):
    """How a run started: by hand or from a schedule tick."""

    manual = "manual"
    cron = "cron"


class RunStatus(StrEnum):
    """Whole-run outcome, derived from its step runs, never hand-edited."""

    running = "running"
    succeeded = "succeeded"
    attention = "attention"
    cancelled = "cancelled"


class StepState(StrEnum):
    """One step's display state, derived from its task status."""

    waiting = "waiting"
    running = "running"
    done = "done"
    attention = "attention"


STEP_STATE_OF_TASK_STATUS: dict[str, StepState] = {
    "closed": StepState.done,
    "blocked": StepState.attention,
    "in_progress": StepState.running,
    "open": StepState.waiting,
    "deferred": StepState.waiting,
}
"""Task status to step state; anything unknown counts as waiting."""


def step_state_of(task_status: str) -> StepState:
    """Map a bead task status to its step state (unknown means waiting)."""
    return STEP_STATE_OF_TASK_STATUS.get(task_status, StepState.waiting)


@dataclass(frozen=True, slots=True)
class Step:
    """One worker's task template inside a stage."""

    name: str
    title: str
    description: str = ""
    cwd: str | None = None
    coder: str | None = None
    model: str | None = None
    priority: int | None = None
    needs: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Stage:
    """One ordered group of steps; every step in a stage may run in parallel."""

    name: str
    steps: tuple[Step, ...] = ()


@dataclass(frozen=True, slots=True)
class Defaults:
    """Fallback worker settings for steps that leave a field empty."""

    cwd: str | None = None
    coder: str | None = None
    model: str | None = None
    priority: int = 2


@dataclass(frozen=True, slots=True)
class Workflow:
    """One saved, named definition of workers arranged in stages."""

    id: str
    name: str
    description: str = ""
    defaults: Defaults = field(default_factory=Defaults)
    stages: tuple[Stage, ...] = ()
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Return this workflow as plain JSON-safe data."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "defaults": {
                "cwd": self.defaults.cwd,
                "coder": self.defaults.coder,
                "model": self.defaults.model,
                "priority": self.defaults.priority,
            },
            "stages": [
                {
                    "name": stage.name,
                    "steps": [_step_to_dict(step) for step in stage.steps],
                }
                for stage in self.stages
            ],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Workflow:
        """Build a workflow from stored data."""
        raw_defaults = data.get("defaults") or {}
        if not isinstance(raw_defaults, dict):
            raise ValueError("defaults: must be a mapping")
        stages = tuple(_stage_from_dict(item) for item in data.get("stages") or [])
        return cls(
            id=str(data.get("id", "")),
            name=str(data.get("name", "")),
            description=str(data.get("description", "")),
            defaults=Defaults(
                cwd=raw_defaults.get("cwd"),
                coder=raw_defaults.get("coder"),
                model=raw_defaults.get("model"),
                priority=int(raw_defaults.get("priority", 2)),
            ),
            stages=stages,
            created_at=str(data.get("created_at", "")),
            updated_at=str(data.get("updated_at", "")),
        )


@dataclass(frozen=True, slots=True)
class WorkflowRun:
    """One execution of a workflow, with the definition frozen at start."""

    id: str
    workflow_id: str
    n: int
    trigger: Trigger
    schedule_id: str | None
    spec: Workflow
    status: RunStatus
    reason: str = ""
    started_at: str = ""
    finished_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return this run as plain JSON-safe data."""
        return {
            "id": self.id,
            "workflow_id": self.workflow_id,
            "n": self.n,
            "trigger": self.trigger.value,
            "schedule_id": self.schedule_id,
            "spec": self.spec.to_dict(),
            "status": self.status.value,
            "reason": self.reason,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorkflowRun:
        """Build a run from stored data."""
        return cls(
            id=str(data.get("id", "")),
            workflow_id=str(data.get("workflow_id", "")),
            n=int(data.get("n", 0)),
            trigger=_trigger_from(data.get("trigger")),
            schedule_id=data.get("schedule_id"),
            spec=Workflow.from_dict(data.get("spec") or {}),
            status=_status_from(data.get("status")),
            reason=str(data.get("reason", "")),
            started_at=str(data.get("started_at", "")),
            finished_at=data.get("finished_at"),
        )


@dataclass(frozen=True, slots=True)
class StepRun:
    """One step inside one run: its task id and last known task status."""

    run_id: str
    step_name: str
    stage_index: int
    task_id: str
    task_status: str
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        """Return this step run as plain JSON-safe data."""
        return {
            "run_id": self.run_id,
            "step_name": self.step_name,
            "stage_index": self.stage_index,
            "task_id": self.task_id,
            "task_status": self.task_status,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StepRun:
        """Build a step run from stored data."""
        return cls(
            run_id=str(data.get("run_id", "")),
            step_name=str(data.get("step_name", "")),
            stage_index=int(data.get("stage_index", 0)),
            task_id=str(data.get("task_id", "")),
            task_status=str(data.get("task_status", "")),
            updated_at=str(data.get("updated_at", "")),
        )


def _step_to_dict(step: Step) -> dict[str, Any]:
    """Return one step as plain JSON-safe data."""
    return {
        "name": step.name,
        "title": step.title,
        "description": step.description,
        "cwd": step.cwd,
        "coder": step.coder,
        "model": step.model,
        "priority": step.priority,
        "needs": list(step.needs),
    }


def _step_from_dict(data: dict[str, Any]) -> Step:
    """Build one step from stored data."""
    needs = data.get("needs") or []
    return Step(
        name=str(data.get("name", "")),
        title=str(data.get("title", "")),
        description=str(data.get("description", "")),
        cwd=data.get("cwd"),
        coder=data.get("coder"),
        model=data.get("model"),
        priority=data.get("priority"),
        needs=tuple(str(item) for item in needs),
    )


def _stage_from_dict(data: dict[str, Any]) -> Stage:
    """Build one stage from stored data."""
    steps = tuple(_step_from_dict(item) for item in data.get("steps") or [])
    return Stage(name=str(data.get("name", "")), steps=steps)


def _trigger_from(raw: Any) -> Trigger:
    """Parse a trigger value, rejecting anything unknown."""
    try:
        return Trigger(str(raw))
    except ValueError:
        raise ValueError(f"trigger: unknown trigger {raw!r}") from None


def _status_from(raw: Any) -> RunStatus:
    """Parse a run status value, rejecting anything unknown."""
    try:
        return RunStatus(str(raw))
    except ValueError:
        raise ValueError(f"status: unknown run status {raw!r}") from None


def validate(workflow: Workflow) -> list[str]:
    """Check every stage/needs rule; return human-readable problems."""
    problems: list[str] = []
    if not workflow.stages:
        problems.append("stages: workflow has no stages")
    if not _priority_ok(workflow.defaults.priority):
        problems.append(_priority_problem("defaults", workflow.defaults.priority))
    stage_of: dict[str, int] = {}
    seen: set[str] = set()
    for stage_index, stage in enumerate(workflow.stages):
        if not stage.steps:
            problems.append(f"stage {stage.name!r}: has no steps")
        for step in stage.steps:
            problems.extend(_validate_step(step, workflow.defaults))
            if step.name in seen:
                problems.append(f"step {step.name!r}: duplicate step name")
            else:
                seen.add(step.name)
                stage_of[step.name] = stage_index
    for stage_index, stage in enumerate(workflow.stages):
        for step in stage.steps:
            for need in step.needs:
                problems.extend(_validate_need(step.name, need, stage_index, stage_of))
    return problems


def _priority_ok(priority: int | None) -> bool:
    """Check one priority value sits in the 0-4 range."""
    return (
        isinstance(priority, int)
        and not isinstance(priority, bool)
        and _PRIORITY_MIN <= priority <= _PRIORITY_MAX
    )


def _priority_problem(where: str, priority: int | None) -> str:
    """Describe one out-of-range priority value."""
    return f"{where}: priority {priority!r} is outside 0-4"


def _validate_step(step: Step, defaults: Defaults) -> list[str]:
    """Check one step's own fields (name shape, title, priority)."""
    found: list[str] = []
    if not _STEP_NAME_RE.match(step.name):
        found.append(f"step {step.name!r}: name must match ^[a-z0-9][a-z0-9_-]{{0,39}}$")
    if not step.title.strip():
        found.append(f"step {step.name!r}: title must not be empty")
    priority = step.priority if step.priority is not None else defaults.priority
    if not _priority_ok(priority):
        found.append(_priority_problem(f"step {step.name!r}", priority))
    return found


def _validate_need(
    step_name: str, need: str, stage_index: int, stage_of: dict[str, int]
) -> list[str]:
    """Check one `needs` entry names a step from an earlier stage."""
    if need not in stage_of:
        return [f"step {step_name!r}: needs unknown step {need!r}"]
    if stage_of[need] >= stage_index:
        return [f"step {step_name!r}: needs {need!r} from the same or a later stage"]
    return []


def ensure_valid(workflow: Workflow) -> Workflow:
    """Return the workflow, or raise WorkflowInvalid with every problem."""
    problems = validate(workflow)
    if problems:
        raise WorkflowInvalid(problems)
    return workflow


def dependencies_of(workflow: Workflow, stage_index: int, step: Step) -> tuple[str, ...]:
    """Step dependencies: explicit needs, else fan-in from the previous stage."""
    if step.needs:
        return tuple(step.needs)
    if stage_index <= 0 or stage_index > len(workflow.stages):
        return ()
    previous = workflow.stages[stage_index - 1].steps
    return tuple(item.name for item in previous)


def effective(step: Step, defaults: Defaults) -> Step:
    """Fill the step's empty worker fields from the workflow defaults."""
    return replace(
        step,
        cwd=step.cwd if step.cwd is not None else defaults.cwd,
        coder=step.coder if step.coder is not None else defaults.coder,
        model=step.model if step.model is not None else defaults.model,
        priority=step.priority if step.priority is not None else defaults.priority,
    )


def _base36_suffix(length: int = 8) -> str:
    """Random lowercase base36 string for workflow and run ids."""
    return "".join(secrets.choice(_BASE36) for _ in range(length))


def new_id() -> str:
    """Return a fresh workflow id: `wf-` plus 8 lowercase base36 chars."""
    return "wf-" + _base36_suffix()


def new_run_id() -> str:
    """Return a fresh run id: `wfr-` plus 8 lowercase base36 chars."""
    return "wfr-" + _base36_suffix()
