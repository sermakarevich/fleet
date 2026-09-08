"""Tests for prompts.render prompt modes (fresh/continue/validate)."""

from pathlib import Path

from fleet.core.launch import LaunchPlan
from fleet.core.task import Task
from fleet.prompts import PromptContext, render


def _task() -> Task:
    return Task(id="t-001", title="T", description="D", status="in_progress")


def _ctx(task_dir: Path, plan: LaunchPlan | None) -> PromptContext:
    pack = plan.pack if plan is not None else ""
    return PromptContext(task=_task(), task_dir=task_dir, pack=pack)


def test_render_validate_uses_validate_instructions(tmp_path: Path) -> None:
    plan = LaunchPlan(mode="validate", pack="kids digest", pack_bytes=11, needs_compaction=False)
    prompt = render(plan.mode, _ctx(tmp_path, plan))
    assert "validating a job" in prompt
    assert "kids digest" in prompt
    assert "FLEET_LAUNCH_MODE" not in prompt  # env layering stays in llm_session


def test_render_mode_arg_wins_over_plan(tmp_path: Path) -> None:
    plan = LaunchPlan(mode="continue", pack="", pack_bytes=0, needs_compaction=False)
    prompt = render("validate", _ctx(tmp_path, plan))
    assert "validating a job" in prompt
