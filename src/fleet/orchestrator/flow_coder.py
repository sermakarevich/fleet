"""Coder step runs as real worker processes (DESIGN.md §3.6, §3.8).

A coder step run is executed by the existing worker machinery with a
synthetic :class:`Task`: the run store is the journal for step runs, so —
unlike bead spawns — nothing is recorded in the bead attempts journal and
nothing is added to ``st.running``.

Outputs paths: the worker contract (``docs/WORKER_CONTRACT.md``) says a
coder publishes step outputs at ``$FLEET_TASK_DIR/outputs.json`` (bare),
while the run layout (``runs.run_dir``) publishes them at
``step_dir/outputs/outputs.json`` (nested). Here the task dir *is* the step
dir, so :func:`coder_outcome` looks for the bare file first (what a real
coder writes), then ``attempt_dir/outputs.json``, and copies whichever it
finds to the nested run-layout path that templates read.
"""

from __future__ import annotations

import asyncio
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from fleet.core.task import Task, TaskOutcome, TaskOutcomeRecord
from fleet.orchestrator import spawn
from fleet.runs import run_dir as run_paths
from fleet.runs.run_dir import NO_ITEM
from fleet.runs.store import Run
from fleet.state.artifacts import ResultFile
from fleet.workers import select_worker
from fleet.workers.base import StepContext, WorkerRun

from .reap import fold_declared_result, outcome_of

if TYPE_CHECKING:
    from fleet.orchestrator.state import SupervisorState
    from fleet.runs.engine import Launch


def step_task_id(launch: Launch, run: Run) -> str:
    """Stable id for one step run: ``<run>.<step>`` (plus ``.<index>`` items)."""
    step = launch.step_run.step
    if launch.step_run.item_index == NO_ITEM:
        return f"{run.id}.{step}"
    return f"{run.id}.{step}.{launch.step_run.item_index}"


def step_task(launch: Launch, run: Run) -> Task:
    """Build the synthetic worker Task for a coder step run launch."""
    return Task(
        id=step_task_id(launch, run),
        title=f"{run.flow}/{launch.step_run.step}",
        description=launch.prompt,
        status="in_progress",
        cwd=str(launch.cwd),
        coder=launch.coder,
        model=launch.model,
        worker=None,
        isolation=launch.isolation,
    )


@dataclass(frozen=True)
class FlowWorker:
    """One in-flight coder step run: the launch, its worker, and its dirs."""

    launch: Launch
    run_id: str
    task: Task
    run: WorkerRun
    future: asyncio.Task[TaskOutcomeRecord]
    attempt_dir: Path
    started_at: datetime


def start_coder_step(
    st: SupervisorState, launch: Launch, run: Run, feedback: str = ""
) -> FlowWorker:
    """Launch a coder step run as a real worker process; return its record.

    Resolves the coder with :func:`spawn.resolve_coder` (config defaults
    apply when the task sets none), prepares the workdir with
    :func:`spawn.prepare_workdir`, writes the prompt (plus a trailing
    ``feedback`` section when non-empty) to ``attempt_dir/prompt.md``, and
    starts the worker. The record is NOT added to ``st.running``. Raises
    ``RuntimeError`` when the workdir cannot be prepared and propagates
    worker-selection errors to the caller.
    """
    task = step_task(launch, run)
    coder, coder_name, model = spawn.resolve_coder(st, task)
    task_root = spawn.prepare_workdir(st, task)
    if task_root is None:
        raise RuntimeError(f"terminal: cannot prepare workdir for {task.id}")
    adir = run_paths.attempt_dir(launch.step_dir, launch.attempt)
    adir.mkdir(parents=True, exist_ok=True)
    prompt = launch.prompt if not feedback else f"{launch.prompt}\n\n{feedback}"
    (adir / "prompt.md").write_text(prompt, encoding="utf-8")
    ctx = StepContext(
        task=task,
        task_dir=launch.step_dir,
        workdir=task_root,
        fleet_home=st.fleet_home,
        coder=coder,
        config=st.config,
        rate_gauge=st.rate_gauge,
        log=st.log.bind(task_id=task.id),
        attempt_dir=adir,
        attempt_n=launch.attempt,
        question_store=st.question_store,
        workflow_runner=st.workflow_runner,
    )
    worker = select_worker(task, ctx, st.queue)
    run_handle = WorkerRun(worker, ctx)
    future = asyncio.create_task(run_handle.run(), name=f"flow:{task.id}")
    st.log.info(
        "flow_coder_started",
        task_id=task.id,
        coder=coder_name,
        model=model,
        attempt=launch.attempt,
    )
    return FlowWorker(
        launch=launch,
        run_id=run.id,
        task=task,
        run=run_handle,
        future=future,
        attempt_dir=adir,
        started_at=st.clock.now(),
    )


def copy_declared_outputs(step_dir: Path, attempt_dir: Path) -> Path | None:
    """Copy a coder's declared outputs into the run-layout outputs file.

    Looks for the worker-contract file (``step_dir/outputs.json``) first,
    then ``attempt_dir/outputs.json``; copies the first one found to
    ``step_dir/outputs/outputs.json``. Returns the written path, or None
    when the coder published nothing.
    """
    for candidate in (step_dir / "outputs.json", attempt_dir / "outputs.json"):
        if candidate.is_file():
            target = run_paths.outputs_file(step_dir)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(candidate, target)
            return target
    return None


def coder_outcome(worker: FlowWorker) -> tuple[bool, str]:
    """Fold a finished coder step run into ``(ok, reason)`` plus outputs copy.

    ``ok`` when the folded outcome is success: the raw future outcome via
    :func:`reap.outcome_of`, folded with the live ``RESULT.json`` declaration
    (read off the step dir, the worker's task dir) via
    :func:`reap.fold_declared_result` for ``SUCCESS`` exits. Always copies
    declared outputs into the run layout (see :func:`copy_declared_outputs`).
    """
    record = outcome_of(worker.future)
    if record.outcome is TaskOutcome.SUCCESS:
        result = ResultFile.read_declared(worker.launch.step_dir)
        if result is not None:
            record = fold_declared_result(record, result)
    copy_declared_outputs(worker.launch.step_dir, worker.attempt_dir)
    return record.outcome is TaskOutcome.SUCCESS, record.reason
