"""The `task` family: fresh vs. continue launch, decided in Python.

``plan_task`` is the family's `plan(ctx)` entry point (see
``workers/__init__.py``). It reads this task's STATE.md and attempt
history through `core.launch.plan_launch` and picks ``FreshTask`` (no
prior attempts, STATE.md still the stub), ``ContinueLargeTask`` (continue
with ``LaunchPlan.needs_compaction`` — a ``Compact`` step first), or
``ContinueTask`` (everything else).
"""

from __future__ import annotations

from pathlib import Path

from fleet.core.launch import LaunchLimits, LaunchPlan, plan_launch
from fleet.core.task import AttemptKind
from fleet.state.artifacts import StateFile, read_artifacts
from fleet.state.attempts import load_attempts

from .base import FnStep, Step, StepContext, StepResult, StepStatus, Worker, merge_run_json
from .compact import COMPACT_STEP
from .llm_session import LlmSession


def _ensure_state(task_dir: Path, task_id: str) -> None:
    """Create the STATE.md stub and outputs/ if missing.

    Never overwrites existing content — the worker owns STATE.md after
    the first run.
    """
    StateFile.ensure_stub(task_dir, task_id)


def _record_launch(ctx: StepContext, plan) -> None:
    """Record this attempt's launch decision in run.json["launch"].

    Read back by `state/artifacts.py` (previous-attempt RESULT comes from
    the snapshot, launch mode from here) and `state/attempt_summary.py`.
    """
    merge_run_json(
        ctx,
        launch={
            "mode": plan.mode,
            "pack_bytes": plan.pack_bytes,
            "kind": AttemptKind.WORK.value,
        },
    )


def _launch_limits(ctx: StepContext) -> LaunchLimits:
    return LaunchLimits(
        continue_pack_max_bytes=ctx.config.continue_pack_max_bytes,
        state_max_bytes=ctx.config.state_max_bytes,
    )


def _plan_launch_for(ctx: StepContext):
    """Read STATE.md + attempt history and decide this attempt's LaunchPlan."""
    attempts_before = [a for a in load_attempts(ctx.task_dir) if a["n"] < ctx.attempt_n]
    artifacts = read_artifacts(ctx.task_dir, ctx.task.id, before_n=ctx.attempt_n)
    return plan_launch(attempts_before, artifacts, _launch_limits(ctx))


async def prepare_artifacts(ctx: StepContext) -> StepResult:
    """Seed the STATE.md stub and record a fresh launch in run.json."""
    _ensure_state(ctx.task_dir, ctx.task.id)
    fresh_plan = LaunchPlan(mode="fresh", pack="", pack_bytes=0, needs_compaction=False)
    ctx.plan = fresh_plan
    _record_launch(ctx, fresh_plan)
    assert ctx.coder is not None
    hook = getattr(ctx.coder, "write_runtime_config", None)
    if hook is not None:
        hook(ctx.project_root, ctx.task)
    return StepResult(status=StepStatus.OK)


async def prepare_continue(ctx: StepContext) -> StepResult:
    """Plan the continue launch pack, store it for LlmSession, record it in run.json."""
    plan = _plan_launch_for(ctx)
    ctx.plan = plan
    ctx.launch_plan = plan
    _record_launch(ctx, plan)
    assert ctx.coder is not None
    hook = getattr(ctx.coder, "write_runtime_config", None)
    if hook is not None:
        hook(ctx.project_root, ctx.task)
    return StepResult(status=StepStatus.OK)


PREPARE_ARTIFACTS = FnStep("prepare_artifacts", prepare_artifacts)
PREPARE_CONTINUE = FnStep("prepare_continue", prepare_continue)


FreshTask = Worker("task.fresh", (PREPARE_ARTIFACTS, LlmSession()))
ContinueTask = Worker("task.continue", (PREPARE_CONTINUE, LlmSession()))
ContinueLargeTask = Worker("task.continue_large", (COMPACT_STEP, PREPARE_CONTINUE, LlmSession()))


def plan_task(ctx: StepContext) -> Worker:
    """Pick the task-family worker: fresh, continue, or continue-large.

    Computes the same `read_artifacts` + `plan_launch` inputs the
    prepare_continue step will use, purely to decide which worker to run; `PrepareContinue` (when
    chosen) recomputes the plan itself rather than receiving it here, since a
    worker is a static list of steps with no room to smuggle data in.
    The compact step runs first on the large path and prepare_continue re-plans on
    the compacted STATE.md, so the session never re-reads huge logs.

    A fresh ``Worker`` (with fresh step instances) is built on every call
    rather than reusing a module-level singleton, because ``LlmSession``
    holds per-attempt subprocess state on ``self`` and attempts run
    concurrently across tasks.
    """
    plan = _plan_launch_for(ctx)
    if plan.mode == "fresh":
        steps: tuple[Step, ...] = (PREPARE_ARTIFACTS, LlmSession())
        return Worker(FreshTask.name, steps)
    if plan.needs_compaction and ctx.config.compaction_enabled:
        steps = (COMPACT_STEP, PREPARE_CONTINUE, LlmSession())
        return Worker(ContinueLargeTask.name, steps)
    steps = (PREPARE_CONTINUE, LlmSession())
    return Worker(ContinueTask.name, steps)
