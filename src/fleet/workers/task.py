"""The `task` family: today's single "run one coder attempt" worker.

``plan_task`` is the family's `plan(ctx)` entry point (see
``workers/__init__.py``). It currently always builds a fresh
``FreshTask``-shaped worker; launch modes (continue, continue-with-
compaction) are a later bead and will branch here on the task directory's
artifacts and attempt history.
"""

from __future__ import annotations

from pathlib import Path

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


class PrepareArtifacts:
    """Seed artifact stubs, rotate the previous RESULT.json, write coder config."""

    name = "prepare_artifacts"

    async def run(self, ctx: StepContext) -> StepResult:
        artifacts_dir = ctx.task_dir / "artifacts"
        _ensure_artifact_stubs(artifacts_dir, ctx.task.id)
        _rotate_result(artifacts_dir)
        assert ctx.coder is not None
        ctx.coder.write_runtime_config(ctx.project_root, ctx.task)
        return StepResult(status="ok")

    async def cancel(self, reason: str) -> None:
        return None


FreshTask = Worker("task.fresh", (PrepareArtifacts(), LlmSession()))


def plan_task(ctx: StepContext) -> Worker:
    """Pick the task-family worker for this attempt.

    Always ``FreshTask`` today. A fresh ``Worker`` (with fresh step
    instances) is built on every call rather than reusing the module-level
    ``FreshTask`` singleton, because ``LlmSession`` holds per-attempt
    subprocess state on ``self`` and attempts run concurrently across tasks.
    """
    steps: tuple[Step, ...] = (PrepareArtifacts(), LlmSession())
    return Worker(FreshTask.name, steps)
