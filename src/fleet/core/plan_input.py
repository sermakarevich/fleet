"""The narrow input every worker-family planner reads.

Called by ``workers/__init__.py`` (``select_worker`` builds one per attempt)
and the three planners (``plan_task``, ``plan_job``, ``plan_observer``).
A planner sees only the task, its directory, the runtime config, and the
attempt number — everything else on ``StepContext`` (coder, queue, store,
runner, clock) stays with the steps that use it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from fleet.core.config import RuntimeConfig
from fleet.core.task import Task


@dataclass(frozen=True, slots=True)
class PlanInput:
    """What a planner may read: task, task dir, config, attempt number."""

    task: Task
    task_dir: Path
    config: RuntimeConfig
    attempt_n: int = 0
