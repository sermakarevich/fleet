"""Shared supervisor state: one blackboard every service reads and writes."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

from fleet.beads.queue import Queue
from fleet.coders.base import Coder
from fleet.core.clock import Clock, SystemClock
from fleet.core.config import RuntimeConfig
from fleet.core.task import Task, TaskOutcomeRecord
from fleet.integrations.ask_human.store import QuestionStore
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
    fleet_home: Path
    runtime_toml_path: Path
    queue: Queue
    log: structlog.BoundLogger
    rate_gauge: RateGauge
    # How to build a coder from (coder_name, model). Tests inject a fake
    # here; None means the production coders.resolve_coder in spawn.py.
    coder_factory: Callable[[str, str | None], Coder] | None = None
    running: dict[str, RunningWorker] = field(
        default_factory=dict
    )  # writer: Claim adds, Reap removes (beads 3-4)
    paused_until: datetime | None = None  # writer: Reap sets, Claim clears
    shutting_down: bool = False  # writer: Supervisor
    # Writer: Supervisor runner fills this before on_start so services
    # (e.g. ConfigReload) can emit events to each other via emit().
    services: list[Service] = field(default_factory=list)
    # Writer: the CLI entry point injects the shared ask_human store once;
    # spawn.py forwards it to StepContext.
    question_store: QuestionStore | None = None
    # Reader: every service. The injected clock (FakeClock in tests) for
    # now()/monotonic() — no direct datetime.now/time.monotonic in services.
    clock: Clock = field(default_factory=SystemClock)
    # Owner: StallWatch adds supervised kill tasks; the supervisor drains
    # them on shutdown so no kill is garbage-collected mid-flight.
    background: set[asyncio.Task] = field(default_factory=set)

    def task_dir_for(self, task_id: str) -> Path:
        """Return the task directory for a task id."""
        return state_paths.task_dir(self.fleet_home, task_id)
