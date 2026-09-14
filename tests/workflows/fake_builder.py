"""Fake builder for tests: one stage with two steps."""

from __future__ import annotations

from dataclasses import replace

from fleet.workflows.builders import BuildContext
from fleet.workflows.model import Stage, Step, Workflow


def build(workflow: Workflow, ctx: BuildContext) -> Workflow:
    """Return the workflow with one concrete stage (ignores ctx except inputs)."""
    _ = ctx
    return replace(
        workflow,
        stages=(
            Stage(
                name="s1",
                steps=(
                    Step(name="a", title="A {{inputs.url}}", description=""),
                    Step(name="b", title="B", description=""),
                ),
            ),
        ),
    )
