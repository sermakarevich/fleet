"""Every launch mode renders; every referenced template file exists."""

from pathlib import Path

from fleet.core.launch_policy import LaunchPlan
from fleet.core.task import Task
from fleet.prompts import MODE_TEMPLATES, PromptContext, render

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent.parent / "src" / "fleet" / "templates"


def _task() -> Task:
    return Task(id="t-001", title="T", description="D", status="in_progress")


def _ctx(tmp_path: Path, plan: LaunchPlan | None = None) -> PromptContext:
    pack = plan.pack if plan is not None else ""
    return PromptContext(task=_task(), task_dir=tmp_path, pack=pack)


def test_mode_templates_covers_all_modes():
    assert set(MODE_TEMPLATES) == {"fresh", "continue", "validate", "research", "design"}


def test_every_referenced_template_file_exists():
    missing = [
        name
        for template_set in MODE_TEMPLATES.values()
        for name in template_set.files
        if not (_TEMPLATES_DIR / name).exists()
    ]
    assert not missing, f"MODE_TEMPLATES references missing files: {missing}"


def test_every_mode_renders_task_fields(tmp_path: Path):
    for mode in MODE_TEMPLATES:
        prompt = render(mode, _ctx(tmp_path))
        assert "t-001" in prompt
        assert "Fleet Task Protocol" in prompt
        assert "ask_human" in prompt


def test_unknown_mode_falls_back_to_fresh(tmp_path: Path):
    assert render("nope", _ctx(tmp_path)) == render("fresh", _ctx(tmp_path))


def test_pack_is_included_when_present(tmp_path: Path):
    plan = LaunchPlan(mode="continue", pack="the pack", pack_bytes=8, needs_compaction=False)
    assert "the pack" in render(plan.mode, _ctx(tmp_path, plan))


def test_isolated_task_appends_protocol(tmp_path: Path):
    ctx = PromptContext(
        task=_task(),
        task_dir=tmp_path,
        workdir="/wt",
        worktree="/wt",
        isolated=True,
    )
    prompt = render("fresh", ctx)
    assert "Do NOT run `fleet bd close`" in prompt
    assert "/wt" in prompt


def test_non_isolated_task_omits_protocol(tmp_path: Path):
    assert "Do NOT run `fleet bd close`" not in render("fresh", _ctx(tmp_path))
