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
from fleet.state.artifacts import read_artifacts
from fleet.state.attempts import load_attempts
from fleet.state.paths import OUTPUTS_DIR, STATE_MD

from .base import Step, StepContext, StepResult, Worker, merge_run_json
from .compact import Compact
from .llm_session import LlmSession

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"


def _ensure_state(task_dir: Path, task_id: str) -> None:
    """Create the STATE.md stub and outputs/ if missing.

    Never overwrites existing content — the worker owns STATE.md after
    the first run.
    """
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / OUTPUTS_DIR).mkdir(parents=True, exist_ok=True)
    target = task_dir / STATE_MD
    if target.exists():
        return
    tmpl = (_TEMPLATES_DIR / "STATE.md.tmpl").read_text(encoding="utf-8")
    target.write_text(tmpl.format(task_id=task_id), encoding="utf-8")


def _record_launch(ctx: StepContext, plan) -> None:
    """Record this attempt's launch decision in run.json["launch"].

    Read back by `state/artifacts.py` (previous-attempt RESULT comes from
    the snapshot, launch mode from here) and `state/attempt_summary.py`.
    """
    merge_run_json(
        ctx,
        launch={"mode": plan.mode, "pack_bytes": plan.pack_bytes, "kind": "work"},
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


class PrepareArtifacts:
    """Seed the STATE.md stub and record a fresh launch in run.json.

    The fresh-launch prepare step: no continuation pack, launch always
    records ``mode="fresh"``.
    """

    name = "prepare_artifacts"

    async def run(self, ctx: StepContext) -> StepResult:
        _ensure_state(ctx.task_dir, ctx.task.id)
        fresh_plan = LaunchPlan(mode="fresh", pack="", pack_bytes=0, needs_compaction=False)
        _record_launch(ctx, fresh_plan)
        assert ctx.coder is not None
        ctx.coder.write_runtime_config(ctx.project_root, ctx.task)
        return StepResult(status="ok")

    async def cancel(self, reason: str) -> None:
        return None


class PrepareContinue:
    """The continue-launch prepare step: plans the launch pack from this
    task's STATE.md and attempt history, stores it for `LlmSession`, and
    records the decision in this attempt's run.json."""

    name = "prepare_continue"

    async def run(self, ctx: StepContext) -> StepResult:
        plan = _plan_launch_for(ctx)
        ctx.scratch["launch_plan"] = plan
        _record_launch(ctx, plan)
        assert ctx.coder is not None
        ctx.coder.write_runtime_config(ctx.project_root, ctx.task)
        return StepResult(status="ok")

    async def cancel(self, reason: str) -> None:
        return None


FreshTask = Worker("task.fresh", (PrepareArtifacts(), LlmSession()))
ContinueTask = Worker("task.continue", (PrepareContinue(), LlmSession()))
ContinueLargeTask = Worker(
    "task.continue_large", (Compact(), PrepareContinue(), LlmSession())
)


def plan_task(ctx: StepContext) -> Worker:
    """Pick the task-family worker: fresh, continue, or continue-large.

    Computes the same `read_artifacts` + `plan_launch` inputs `PrepareContinue`
    will use, purely to decide which worker to run; `PrepareContinue` (when
    chosen) recomputes the plan itself rather than receiving it here, since a
    worker is a static list of steps with no room to smuggle data in.
    `Compact` runs first on the large path and `PrepareContinue` re-plans on
    the compacted STATE.md, so the session never re-reads huge logs.

    A fresh ``Worker`` (with fresh step instances) is built on every call
    rather than reusing a module-level singleton, because ``LlmSession``
    holds per-attempt subprocess state on ``self`` and attempts run
    concurrently across tasks.
    """
    plan = _plan_launch_for(ctx)
    if plan.mode == "fresh":
        steps: tuple[Step, ...] = (PrepareArtifacts(), LlmSession())
        return Worker(FreshTask.name, steps)
    if plan.needs_compaction and ctx.config.compaction_enabled:
        steps = (Compact(), PrepareContinue(), LlmSession())
        return Worker(ContinueLargeTask.name, steps)
    steps = (PrepareContinue(), LlmSession())
    return Worker(ContinueTask.name, steps)
