"""Template tests: every placeholder, unknown kept, missing task id kept."""

from __future__ import annotations

from fleet.workflows.templates import TemplateContext, render, render_with_missing


def _ctx(**overrides) -> TemplateContext:
    """Build a render context with known task ids."""
    base: dict = {
        "workflow_name": "nightly",
        "run_id": "wfr-abc12345",
        "run_n": 3,
        "run_date": "2026-09-09",
        "step_name": "summary",
        "task_ids": {"lint": "fleet-aaa", "tests": "fleet-bbb"},
    }
    base.update(overrides)
    return TemplateContext(**base)


def test_render_every_placeholder() -> None:
    text = (
        "{{workflow.name}} {{run.id}} {{run.n}} {{run.date}} {{step.name}} {{steps.lint.task_id}}"
    )
    assert render(text, _ctx()) == ("nightly wfr-abc12345 3 2026-09-09 summary fleet-aaa")


def test_render_unknown_placeholder_kept() -> None:
    assert render("hi {{nope}} bye", _ctx()) == "hi {{nope}} bye"


def test_render_unknown_dotted_placeholder_kept() -> None:
    assert render("{{run.hour}}", _ctx()) == "{{run.hour}}"


def test_render_missing_task_id_kept() -> None:
    assert render("{{steps.future.task_id}}", _ctx()) == "{{steps.future.task_id}}"


def test_render_malformed_step_reference_kept() -> None:
    assert render("{{steps.lint}}", _ctx()) == "{{steps.lint}}"


def test_render_plain_text_untouched() -> None:
    assert render("no placeholders here", _ctx()) == "no placeholders here"


def test_render_input_resolves() -> None:
    ctx = _ctx(inputs={"paper_url": "https://example.test/paper"})
    assert render("Fetch {{inputs.paper_url}}!", ctx) == "Fetch https://example.test/paper!"


def test_render_unknown_input_kept() -> None:
    assert render("{{inputs.missing}}", _ctx()) == "{{inputs.missing}}"


def test_render_step_outputs_missing_renders_empty_and_reports() -> None:
    text = "{{steps.fetch.outputs.pdf_path}}"
    filled, missing = render_with_missing(text, _ctx(inputs={"paper_url": "x"}))
    assert filled == ""
    assert missing == ["steps.fetch.outputs.pdf_path"]


def test_render_step_outputs_resolves() -> None:
    ctx = _ctx(step_outputs={"fetch": {"pdf_path": "/tmp/paper.pdf"}})
    filled, missing = render_with_missing("Read {{steps.fetch.outputs.pdf_path}}.", ctx)
    assert filled == "Read /tmp/paper.pdf."
    assert missing == []


def test_render_step_outputs_unknown_step_reports() -> None:
    filled, missing = render_with_missing("{{steps.ghost.outputs.key}}", _ctx())
    assert filled == ""
    assert missing == ["steps.ghost.outputs.key"]


def test_render_with_missing_clean_render_reports_nothing() -> None:
    filled, missing = render_with_missing("Lint {{workflow.name}} {{steps.lint.task_id}}", _ctx())
    assert filled == "Lint nightly fleet-aaa"
    assert missing == []
