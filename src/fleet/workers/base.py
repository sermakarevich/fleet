"""The step/worker shapes every family plugs into. See ADR 0003.

A ``Step`` is atomic and knows nothing about beads status. A ``Worker`` is a
named, ordered tuple of steps. ``run_worker`` drives one worker run and is
the only place that decides how a worker's outcome is derived from its
steps; ``WorkerRun`` is the handle the orchestrator keeps per in-flight task.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol

import structlog

from fleet.coders.base import Coder
from fleet.core.config import RuntimeConfig
from fleet.core.task import Event, Task, TaskOutcome, TaskOutcomeRecord
from fleet.state.paths import RUN_JSON


class RateGauge(Protocol):
    def update(self, evt: Event) -> None: ...


@dataclass
class StepContext:
    task: Task
    task_dir: Path  # tasks/<id>
    project_root: Path  # where the coder runs (cwd or worktree)
    fleet_home: Path
    coder: Coder | None
    config: RuntimeConfig
    rate_gauge: RateGauge
    log: structlog.BoundLogger
    # Per-attempt directory (tasks/<id>/attempts/<n>) and its number. Set by
    # orchestrator/spawn.py from attempts.record_start's return value before
    # the worker is planned/run. Defaulted here (rather than required) so
    # tests that build a StepContext directly without an attempt still work;
    # run_worker() falls back to task_dir when attempt_dir is None.
    attempt_dir: Path | None = None
    attempt_n: int = 0
    # Small values passed forward between steps (e.g. prompt text). Never
    # file contents > 16 KB.
    scratch: dict[str, Any] = field(default_factory=dict)


@dataclass
class StepResult:
    status: Literal["ok", "fail", "outcome"]
    reason: str = ""
    # Only set for status == "outcome" (the session step).
    outcome: TaskOutcomeRecord | None = None


class Step(Protocol):
    name: str

    async def run(self, ctx: StepContext) -> StepResult: ...

    async def cancel(self, reason: str) -> None:
        """Interrupt this step while it is running. Default is a no-op.

        ``llm_session`` is the step that overrides this to signal the
        process group; steps with no subprocess have nothing to interrupt.
        """
        return None


@dataclass(frozen=True)
class Worker:
    name: str  # "task.fresh" — recorded in attempts.jsonl and run.json
    steps: tuple[Step, ...]


def _read_run_json(run_file: Path) -> dict:
    try:
        return json.loads(run_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def write_run_json(run_file: Path, **updates: Any) -> None:
    """Read-merge-write run.json so sequential step writers never clobber
    each other's keys (a step may run after another step already wrote its
    own fields, e.g. pid/exit_code, into the same file)."""
    data = _read_run_json(run_file)
    data.update(updates)
    run_file.parent.mkdir(parents=True, exist_ok=True)
    tmp = run_file.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    tmp.replace(run_file)


def merge_run_json(ctx: StepContext, **updates: Any) -> None:
    """Merge *updates* into this attempt's run.json via the atomic writer.

    Steps that need to record their own keys (e.g. the prepare steps'
    ``launch`` record) call this instead of writing run.json themselves,
    so concurrent writers (the llm_session heartbeat) never lose keys.
    """
    write_run_json((ctx.attempt_dir or ctx.task_dir) / RUN_JSON, **updates)


def _record_step(
    run_file: Path,
    worker_name: str,
    entry: dict,
) -> None:
    data = _read_run_json(run_file)
    data["worker"] = worker_name
    steps = data.get("steps")
    if not isinstance(steps, list):
        steps = []
    steps.append(entry)
    data["steps"] = steps
    run_file.parent.mkdir(parents=True, exist_ok=True)
    tmp = run_file.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    tmp.replace(run_file)


def _now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


async def run_worker(
    worker: Worker,
    ctx: StepContext,
    *,
    on_step: Callable[[Step | None], None] | None = None,
) -> TaskOutcomeRecord:
    """Run *worker*'s steps in order against *ctx*.

    Stops at the first ``fail`` (-> FAILURE) or ``outcome`` (-> that
    outcome); an all-``ok`` run is SUCCESS. Each step's timing and status is
    appended to ``run.json["steps"]``. An unexpected exception inside a step
    is caught and reported as FAILURE.
    """
    run_file = (ctx.attempt_dir or ctx.task_dir) / RUN_JSON
    for step in worker.steps:
        if on_step is not None:
            on_step(step)
        started_at = _now_iso()
        try:
            result = await step.run(ctx)
        except Exception as exc:  # noqa: BLE001 - step contract: never propagate
            ended_at = _now_iso()
            _record_step(
                run_file,
                worker.name,
                {
                    "name": step.name,
                    "started_at": started_at,
                    "ended_at": ended_at,
                    "status": "fail",
                    "reason": f"unexpected exception: {exc}",
                },
            )
            if on_step is not None:
                on_step(None)
            return TaskOutcomeRecord(
                outcome=TaskOutcome.FAILURE,
                reason=f"unexpected exception: {exc}",
            )
        ended_at = _now_iso()
        _record_step(
            run_file,
            worker.name,
            {
                "name": step.name,
                "started_at": started_at,
                "ended_at": ended_at,
                "status": result.status,
                "reason": result.reason,
            },
        )
        if on_step is not None:
            on_step(None)
        if result.status == "fail":
            return TaskOutcomeRecord(
                outcome=TaskOutcome.FAILURE,
                reason=f"step {step.name}: {result.reason}",
            )
        if result.status == "outcome":
            assert result.outcome is not None
            return result.outcome
    return TaskOutcomeRecord(outcome=TaskOutcome.SUCCESS, exit_code=0)


class WorkerRun:
    """Handle the supervisor keeps per in-flight task (replaces TaskRunner)."""

    def __init__(self, worker: Worker, ctx: StepContext) -> None:
        self.worker = worker
        self._ctx = ctx
        self._current_step: Step | None = None

    def _set_current(self, step: Step | None) -> None:
        self._current_step = step

    async def run(self) -> TaskOutcomeRecord:
        return await run_worker(self.worker, self._ctx, on_step=self._set_current)

    def merge_run_json(self, **updates: Any) -> None:
        """Merge *updates* into this run's attempt run.json (see `merge_run_json`)."""
        merge_run_json(self._ctx, **updates)

    async def kill(self, reason: str = "manual_kill") -> None:
        """Forward to the step currently running."""
        step = self._current_step
        if step is not None:
            await step.cancel(reason)

    async def cancel(self) -> None:
        """Forward a shutdown cancel to the step currently running."""
        step = self._current_step
        if step is not None:
            await step.cancel("supervisor_shutdown")
