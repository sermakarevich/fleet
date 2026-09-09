"""Step text templates: fill run ids and task ids into titles and descriptions.

Called by the run engine when it opens each step's bead: all task ids
exist before any worker starts, so later steps can quote earlier steps'
ids. Unknown placeholders stay as written.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class TemplateContext:
    """Everything one render needs: the workflow, the run, and known task ids."""

    workflow_name: str
    run_id: str
    run_n: int
    run_date: str
    step_name: str
    task_ids: Mapping[str, str]
    inputs: Mapping[str, str] = field(default_factory=dict)
    step_outputs: Mapping[str, Mapping[str, str]] = field(default_factory=dict)


_PLACEHOLDER_RE = re.compile(r"\{\{\s*([A-Za-z0-9_.-]+)\s*\}\}")
_STEP_TASK_RE = re.compile(r"steps\.([a-z0-9][a-z0-9_-]*)\.task_id")
_STEP_OUTPUT_RE = re.compile(r"steps\.([a-z0-9][a-z0-9_-]*)\.outputs\.([A-Za-z0-9_.-]+)")
_INPUT_RE = re.compile(r"inputs\.([a-z][a-z0-9_]*)")


def render_with_missing(text: str, ctx: TemplateContext) -> tuple[str, list[str]]:
    """Fill known `{{placeholders}}`; leave unknown ones exactly as written.

    A `{{steps.<name>.outputs.<key>}}` reference whose step or key is
    unknown renders as the empty string and is reported in the returned
    missing list (as `steps.<name>.outputs.<key>`), so the caller can
    record an `outputs_missing` warning. Every other unknown placeholder
    stays as written and is never reported.
    """
    table = {
        "workflow.name": ctx.workflow_name,
        "run.id": ctx.run_id,
        "run.n": str(ctx.run_n),
        "run.date": ctx.run_date,
        "step.name": ctx.step_name,
    }
    missing: list[str] = []

    def _fill(match: re.Match[str]) -> str:
        """Resolve one placeholder against the lookup table and task ids."""
        key = match.group(1)
        if key in table:
            return table[key]
        step_match = _STEP_TASK_RE.fullmatch(key)
        if step_match is not None:
            wanted = step_match.group(1)
            if wanted in ctx.task_ids:
                return ctx.task_ids[wanted]
        output_match = _STEP_OUTPUT_RE.fullmatch(key)
        if output_match is not None:
            wanted_step, wanted_key = output_match.group(1), output_match.group(2)
            values = ctx.step_outputs.get(wanted_step)
            if values is not None and wanted_key in values:
                return values[wanted_key]
            missing.append(f"steps.{wanted_step}.outputs.{wanted_key}")
            return ""
        input_match = _INPUT_RE.fullmatch(key)
        if input_match is not None:
            wanted = input_match.group(1)
            if wanted in ctx.inputs:
                return ctx.inputs[wanted]
        return match.group(0)

    return _PLACEHOLDER_RE.sub(_fill, text), missing


def render(text: str, ctx: TemplateContext) -> str:
    """Fill known `{{placeholders}}`; leave unknown ones exactly as written."""
    filled, _ = render_with_missing(text, ctx)
    return filled
