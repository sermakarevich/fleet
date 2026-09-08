"""The `task` family: fresh vs. continue launch, decided in Python.

``plan_task`` is the family's `plan(ctx)` entry point (see
``workers/__init__.py``). It reads this task's artifacts and attempt
history through `core.launch.plan_launch` and picks ``FreshTask`` (no
prior attempts, artifacts still stubs) or ``ContinueTask`` (everything
else). A later bead adds ``ContinueLargeTask`` for
``LaunchPlan.needs_compaction``; that flag is only recorded here.
"""

from __future__ import annotations

import json
from pathlib import Path

from fleet.core.launch import LaunchLimits, LaunchPlan, plan_launch
from fleet.state.artifacts import read_artifacts
from fleet.state.attempts import load_attempts

from .base import Step, StepContext, StepResult, Worker
from .llm_session import LlmSession

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"


def _ensure_artifact_stubs(artifacts_dir: Path, task_id: str) -> None:
    """Create PLAN.md, HANDOFF.md, KNOWLEDGE.md stubs and outputs/ if missing.

    Never overwrites existing content — agents own these files after the
    first run.
    """
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    (artifacts_dir / "outputs").mkdir(parents=True, exist_ok=True)
    for name in ("PLAN.md", "HANDOFF.md", "KNOWLEDGE.md"):
        target = artifacts_dir / name
        if target.exists():
            continue
        tmpl = (_TEMPLATES_DIR / f"{name}.tmpl").read_text(encoding="utf-8")
        target.write_text(tmpl.format(task_id=task_id))


def _rotate_result(artifacts_dir: Path) -> None:
    """Move a previous attempt's RESULT.json aside before spawning a new one.

    Spec 2 will move RESULT.json into per-attempt folders; for now the
    previous attempt's declaration is kept at RESULT.prev.json so it does
    not leak into the next attempt's outcome.
    """
    result_file = artifacts_dir / "RESULT.json"
    if not result_file.exists():
        return
    result_file.replace(artifacts_dir / "RESULT.prev.json")


def _write_launch_json(attempt_dir: Path, plan) -> None:
    """Write `attempt_dir/launch.json`, the on-disk record of this attempt's
    launch decision (mode + pack size); read back by `state/artifacts.py`
    and `state/attempt_summary.py`."""
    attempt_dir.mkdir(parents=True, exist_ok=True)
    payload = {"mode": plan.mode, "pack_bytes": plan.pack_bytes, "kind": "work"}
    (attempt_dir / "launch.json").write_text(json.dumps(payload), encoding="utf-8")


def _launch_limits(ctx: StepContext) -> LaunchLimits:
    return LaunchLimits(
        continue_pack_max_bytes=ctx.config.continue_pack_max_bytes,
        handoff_max_bytes=ctx.config.handoff_max_bytes,
        knowledge_max_bytes=ctx.config.knowledge_max_bytes,
    )


def _plan_launch_for(ctx: StepContext):
    """Read artifacts + attempt history and decide this attempt's LaunchPlan."""
    attempts_before = [a for a in load_attempts(ctx.task_dir) if a["n"] < ctx.attempt_n]
    artifacts = read_artifacts(ctx.task_dir, ctx.task.id, before_n=ctx.attempt_n)
    return plan_launch(attempts_before, artifacts, _launch_limits(ctx))


class PrepareArtifacts:
    """Seed artifact stubs, rotate the previous RESULT.json, write coder config.

    The fresh-launch prepare step: no continuation pack, launch.json always
    records ``mode="fresh"``.
    """

    name = "prepare_artifacts"

    async def run(self, ctx: StepContext) -> StepResult:
        artifacts_dir = ctx.task_dir / "artifacts"
        _ensure_artifact_stubs(artifacts_dir, ctx.task.id)
        _rotate_result(artifacts_dir)
        attempt_dir = ctx.attempt_dir or ctx.task_dir
        fresh_plan = LaunchPlan(mode="fresh", pack="", pack_bytes=0, needs_compaction=False)
        _write_launch_json(attempt_dir, fresh_plan)
        assert ctx.coder is not None
        ctx.coder.write_runtime_config(ctx.project_root, ctx.task)
        return StepResult(status="ok")

    async def cancel(self, reason: str) -> None:
        return None


class PrepareContinue:
    """The continue-launch prepare step: plans the launch pack from this
    task's artifacts and attempt history, stores it for `LlmSession`, and
    records the decision in this attempt's launch.json."""

    name = "prepare_continue"

    async def run(self, ctx: StepContext) -> StepResult:
        plan = _plan_launch_for(ctx)
        ctx.scratch["launch_plan"] = plan
        attempt_dir = ctx.attempt_dir or ctx.task_dir
        _write_launch_json(attempt_dir, plan)
        assert ctx.coder is not None
        ctx.coder.write_runtime_config(ctx.project_root, ctx.task)
        return StepResult(status="ok")

    async def cancel(self, reason: str) -> None:
        return None


FreshTask = Worker("task.fresh", (PrepareArtifacts(), LlmSession()))
ContinueTask = Worker("task.continue", (PrepareContinue(), LlmSession()))


def plan_task(ctx: StepContext) -> Worker:
    """Pick the task-family worker for this attempt: fresh or continue.

    Computes the same `read_artifacts` + `plan_launch` inputs `PrepareContinue`
    will use, purely to decide which worker to run; `PrepareContinue` (when
    chosen) recomputes the plan itself rather than receiving it here, since a
    worker is a static list of steps with no room to smuggle data in.

    A fresh ``Worker`` (with fresh step instances) is built on every call
    rather than reusing a module-level singleton, because ``LlmSession``
    holds per-attempt subprocess state on ``self`` and attempts run
    concurrently across tasks.
    """
    plan = _plan_launch_for(ctx)
    if plan.mode == "fresh":
        steps: tuple[Step, ...] = (PrepareArtifacts(), LlmSession())
        return Worker(FreshTask.name, steps)
    steps = (PrepareContinue(), LlmSession())
    return Worker(ContinueTask.name, steps)
