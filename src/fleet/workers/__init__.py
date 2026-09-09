"""Family routing: which `Worker` runs a given bead.

Two levels, per ADR 0003:

1. Family, from the bead (an input, never inferred): bead type routes to a
   family; the optional metadata field ``fleet_worker`` (``Task.worker``)
   overrides. This module does one dictionary lookup.
2. Variant, from the task directory: each family's own ``plan`` function
   looks at its artifacts/attempt history and picks the worker to run. This
   module never inspects the task directory.

``WORKERS`` below is the single registry: the only place a family name
maps to the ``plan`` function that builds its worker. Every plan function
takes the same shape — ``(PlanInput, queue, store)`` — so routing is one
table lookup: ``task`` ignores the queue/store, ``observer`` ignores the
store. The queue and the question store come from the supervisor (the
caller passes ``st.queue`` and the context carries the injected store);
plans and steps never build either. Workers are built fresh per attempt
(``LlmSession`` holds per-attempt subprocess state on ``self``), so the
registry maps names to plan functions, not to worker instances.
``select_worker`` is the single lookup over it.
"""

from __future__ import annotations

from collections.abc import Callable

from fleet.beads.queue import Queue
from fleet.core.plan_input import PlanInput
from fleet.core.task import Task

from .base import QuestionStoreLike, StepContext, Worker
from .job import plan_job
from .observe import plan_observer
from .task_family import plan_task

PlanFn = Callable[[PlanInput, Queue | None, QuestionStoreLike | None], Worker]
"""One planner shape: narrow input, injected queue, injected store."""

WORKERS: dict[str, PlanFn] = {
    "task": lambda plan, queue, store: plan_task(plan),
    "observer": lambda plan, queue, store: plan_observer(plan, _need_queue("observer", queue)),
    "job": lambda plan, queue, store: plan_job(plan, _need_queue("job", queue), store),
}


def _need_queue(family: str, queue: Queue | None) -> Queue:
    """Return *queue*, or raise when a queue-needing family got none."""
    if queue is None:
        raise ValueError(f"family {family!r} needs a queue")
    return queue


_TYPE_TO_FAMILY: dict[str, str] = {
    "task": "task",
    "bug": "task",
    "feature": "task",
    "chore": "task",
    "epic": "observer",
}


def _family_for_type(task_type: str | None) -> str:
    return _TYPE_TO_FAMILY.get(task_type or "task", "task")


def select_worker(task: Task, ctx: StepContext, queue: Queue | None = None) -> Worker:
    """Resolve the worker that should run *task*.

    Raises ``ValueError`` when the family is unknown — the caller
    (``orchestrator/spawn.py``) blocks the bead on this, exactly like an
    invalid coder name.
    """
    family = task.worker or _family_for_type(task.type)
    try:
        plan = WORKERS[family]
    except KeyError:
        raise ValueError(f"no worker for family: {family}") from None
    pin = PlanInput(task=task, task_dir=ctx.task_dir, config=ctx.config, attempt_n=ctx.attempt_n)
    return plan(pin, queue, ctx.question_store)
