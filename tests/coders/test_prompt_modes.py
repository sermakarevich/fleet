"""Tests for coders/base.py prompt modes (fresh/continue/validate)."""

from pathlib import Path

from fleet.coders.base import render_prompt
from fleet.core.launch import LaunchPlan
from fleet.core.task import Task


def _task() -> Task:
    return Task(id="t-001", title="T", description="D", status="in_progress")


def test_render_prompt_validate_uses_validate_instructions(tmp_path: Path) -> None:
    plan = LaunchPlan(mode="validate", pack="kids digest", pack_bytes=11, needs_compaction=False)
    prompt = render_prompt(_task(), tmp_path, plan)
    assert "validating a job" in prompt
    assert "kids digest" in prompt
    assert "FLEET_LAUNCH_MODE" not in prompt  # env layering stays in llm_session


def test_render_prompt_mode_override_wins_over_plan(tmp_path: Path) -> None:
    plan = LaunchPlan(mode="continue", pack="", pack_bytes=0, needs_compaction=False)
    prompt = render_prompt(_task(), tmp_path, plan, mode="validate")
    assert "validating a job" in prompt
