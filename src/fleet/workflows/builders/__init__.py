"""Workflow builders: expand a saved definition into concrete stages at run start.

A plain workflow (ADR 0008) is a fixed graph of stages. Some workflows only
know their shape once a run starts — for example "one worker per chunk of
the source behind this URL". Such a workflow names a *builder* and saves no
stages; `runs.start_run` calls the builder with the run's inputs and plans
the stages it returns. Builders are registered here by name so the model's
validation can reject unknown names without importing builder code (each
builder module is imported on first use only).

Called by `workflows.model` (name check) and `workflows.runs` (expansion).
Builder modules may import `core`, `state`, `beads` and `workflows.model`.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fleet.workflows.model import Workflow

#: Builder name -> module path; every module exposes `build(workflow, ctx)`.
BUILDER_MODULES: dict[str, str] = {
    "summary_get": "fleet.workflows.builders.summary_get",
}


@dataclass(frozen=True, slots=True)
class BuildContext:
    """Everything a builder may use: run identity, resolved inputs, fleet home."""

    run_id: str
    fleet_home: Path
    now: datetime
    inputs: Mapping[str, str] = field(default_factory=dict)

    def work_dir(self, builder: str) -> Path:
        """Per-run scratch folder a builder may write fetched material into."""
        return self.fleet_home / "workflows" / builder / self.run_id


Builder = Callable[["Workflow", BuildContext], "Workflow"]


def builder_names() -> tuple[str, ...]:
    """Every registered builder name, sorted."""
    return tuple(sorted(BUILDER_MODULES))


def get_builder(name: str) -> Builder:
    """The `build` callable of one registered builder; KeyError when unknown."""
    module = importlib.import_module(BUILDER_MODULES[name])
    return module.build  # type: ignore[no-any-return]


def expand(workflow: Workflow, ctx: BuildContext) -> Workflow:
    """Run the workflow's builder (if any) and return the concrete definition."""
    if workflow.builder is None:
        return workflow
    return get_builder(workflow.builder)(workflow, ctx)


__all__ = ["BUILDER_MODULES", "BuildContext", "Builder", "builder_names", "expand", "get_builder"]
