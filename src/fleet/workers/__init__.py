"""Family routing: which `Worker` runs a given bead.

Two levels, per ADR 0003:

1. Family, from the bead (an input, never inferred): bead type routes to a
   family; the optional metadata field ``fleet_worker`` (``Task.worker``)
   overrides. This module does one dictionary lookup.
2. Variant, from the task directory: each family's own ``plan(ctx)``
   function looks at its artifacts/attempt history and picks the worker to
   run. This module never inspects the task directory.
"""

from __future__ import annotations

from collections.abc import Callable

from fleet.core.task import Task

from .base import StepContext, Worker
from .job import plan_job
from .observe import plan_observer
from .task import plan_task

FAMILIES: dict[str, Callable[[StepContext], Worker]] = {
    "task": plan_task,
    "observer": plan_observer,
    "job": plan_job,
}

_TYPE_TO_FAMILY: dict[str, str] = {
    "task": "task",
    "bug": "task",
    "feature": "task",
    "chore": "task",
    "epic": "observer",
}


def _family_for_type(task_type: str | None) -> str:
    return _TYPE_TO_FAMILY.get(task_type or "task", "task")


def select_worker(task: Task, ctx: StepContext) -> Worker:
    """Resolve the worker that should run *task*.

    Raises ``ValueError`` when the family is unknown — the caller
    (``orchestrator/spawn.py``) blocks the bead on this, exactly like an
    invalid coder name.
    """
    family = task.worker or _family_for_type(task.type)
    plan = FAMILIES.get(family)
    if plan is None:
        raise ValueError(f"no worker for family: {family}")
    return plan(ctx)
