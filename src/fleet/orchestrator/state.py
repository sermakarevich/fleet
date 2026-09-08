"""Shared supervisor state: one blackboard every service reads and writes."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

from fleet.beads.queue import Queue
from fleet.coders.base import Coder
from fleet.core.config import RuntimeConfig
from fleet.core.task import Task, TaskOutcomeRecord
from fleet.state import paths as state_paths
from fleet.workers.base import WorkerRun

if TYPE_CHECKING:
    from fleet.orchestrator.rate_gauge import RateGauge
    from fleet.orchestrator.service import Service


@dataclass
class RunningWorker:
    """Everything the supervisor keeps about one in-flight task attempt."""

    task: Task
    run: WorkerRun
    future: asyncio.Task[TaskOutcomeRecord]
    attempt_n: int
    started_at: datetime


@dataclass
class SupervisorState:
    """Shared blackboard. Each field names its single writer in a comment."""

    config: RuntimeConfig  # writer: ConfigReload (bead 2)
    project_root: Path
    runtime_toml_path: Path
    queue: Queue
    log: structlog.BoundLogger
    rate_gauge: RateGauge
    coder_pin: Coder | None = None  # tests only
    running: dict[str, RunningWorker] = field(default_factory=dict)  # writer: Claim adds, Reap removes (beads 3-4)
    paused_until: datetime | None = None  # writer: Reap sets, Claim clears
    shutting_down: bool = False  # writer: Supervisor
    # Writer: Supervisor runner fills this before on_start so services
    # (e.g. ConfigReload) can emit events to each other via emit().
    services: list[Service] = field(default_factory=list)
    # Legacy parallel dicts, owned by Supervisor until bead 3 replaces
    # them with `running`. Writers: Spawn fills, Reap removes.
    in_flight: dict[str, asyncio.Task] = field(default_factory=dict)
    in_flight_tasks: dict[str, Task] = field(default_factory=dict)
    runners: dict[str, WorkerRun] = field(default_factory=dict)
    attempt_n: dict[str, int] = field(default_factory=dict)

    def task_dir_for(self, task_id: str) -> Path:
        """Return the task directory for a task id."""
        return state_paths.task_dir(self.project_root, task_id)
