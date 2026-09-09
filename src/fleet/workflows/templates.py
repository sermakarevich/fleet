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


_PLACEHOLDER_RE = re.compile(r"\{\{\s*([A-Za-z0-9_.-]+)\s*\}\}")
_STEP_TASK_RE = re.compile(r"steps\.([a-z0-9][a-z0-9_-]*)\.task_id")
_INPUT_RE = re.compile(r"inputs\.([a-z][a-z0-9_]*)")


def render(text: str, ctx: TemplateContext) -> str:
    """Fill known `{{placeholders}}`; leave unknown ones exactly as written."""
    table = {
        "workflow.name": ctx.workflow_name,
        "run.id": ctx.run_id,
        "run.n": str(ctx.run_n),
        "run.date": ctx.run_date,
        "step.name": ctx.step_name,
    }

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
        input_match = _INPUT_RE.fullmatch(key)
        if input_match is not None:
            wanted = input_match.group(1)
            if wanted in ctx.inputs:
                return ctx.inputs[wanted]
        return match.group(0)

    return _PLACEHOLDER_RE.sub(_fill, text)
