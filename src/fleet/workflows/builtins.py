"""Built-in workflow definitions: saved on fleet start so the Workflows page
lists every code builder without a manual `fleet workflow import`.

Each builder module may expose a ``DEFINITION`` dict (name, description,
defaults, inputs). ``ensure_builtin_workflows`` saves one workflow per such
builder when the store has none with that name. Existing definitions keep
operator edits (description, defaults); only *new optional inputs* declared
by the builder are backfilled, so older installs accept runs the current
code starts (e.g. research spawning summary_get with research_target).
"""

from __future__ import annotations

import importlib
import logging
from dataclasses import replace
from datetime import datetime
from typing import TYPE_CHECKING, Any

from fleet.workflows.builders import BUILDER_MODULES
from fleet.workflows.model import Defaults, Workflow, WorkflowInput, new_id

if TYPE_CHECKING:
    from fleet.workflows.store import WorkflowStore

logger = logging.getLogger(__name__)


def builtin_definitions() -> list[tuple[str, dict[str, Any]]]:
    """(builder name, DEFINITION) for every builder module that declares one."""
    found: list[tuple[str, dict[str, Any]]] = []
    for name, module_path in sorted(BUILDER_MODULES.items()):
        module = importlib.import_module(module_path)
        definition = getattr(module, "DEFINITION", None)
        if isinstance(definition, dict):
            found.append((name, definition))
    return found


def workflow_from_definition(builder: str, definition: dict[str, Any], now: datetime) -> Workflow:
    """A saved-shape Workflow (fresh id, no stages) from a builder DEFINITION."""
    stamp = now.isoformat()
    raw_defaults = definition.get("defaults") or {}
    return Workflow(
        id=new_id(),
        name=str(definition.get("name") or builder),
        description=str(definition.get("description") or ""),
        defaults=Defaults(
            cwd=raw_defaults.get("cwd"),
            coder=raw_defaults.get("coder"),
            model=raw_defaults.get("model"),
            priority=int(raw_defaults.get("priority", 2)),
            isolation=raw_defaults.get("isolation"),
        ),
        inputs=tuple(
            WorkflowInput(
                name=str(item["name"]),
                description=str(item.get("description") or ""),
                required=bool(item.get("required", False)),
                default=item.get("default"),
            )
            for item in definition.get("inputs") or []
        ),
        builder=builder,
        created_at=stamp,
        updated_at=stamp,
    )


def ensure_builtin_workflows(store: WorkflowStore, now: datetime) -> list[str]:
    """Save every built-in definition the store lacks; return the names added.

    Existing saved workflows keep their id, description and defaults, but
    gain any *optional* inputs the builder declares and the saved copy
    lacks (additive backfill). Required inputs are never backfilled: adding
    one would silently change what a run needs. Returns the names of
    freshly added workflows (backfills do not count as added).
    """
    added: list[str] = []
    for builder, definition in builtin_definitions():
        name = str(definition.get("name") or builder)
        saved = store.get_by_name(name)
        if saved is None:
            store.save(workflow_from_definition(builder, definition, now))
            added.append(name)
            continue
        _backfill_optional_inputs(store, saved, definition, now)
    if added:
        logger.info("registered built-in workflows: %s", ", ".join(added))
    return added


def _backfill_optional_inputs(
    store: WorkflowStore, saved: Workflow, definition: dict[str, Any], now: datetime
) -> None:
    """Add optional builder inputs missing from a saved workflow, in place.

    Operator edits survive: only inputs whose name is absent are appended
    (declaration order preserved); nothing is removed or reordered.
    """

    declared = definition.get("inputs") or []
    have = {item.name for item in saved.inputs}
    missing = [
        WorkflowInput(
            name=str(item["name"]),
            description=str(item.get("description") or ""),
            required=bool(item.get("required", False)),
            default=item.get("default"),
        )
        for item in declared
        if str(item.get("name") or "") and str(item["name"]) not in have
    ]
    missing = [item for item in missing if not item.required]
    if not missing:
        return
    store.save(
        replace(
            saved,
            inputs=tuple(saved.inputs) + tuple(missing),
            updated_at=now.isoformat(),
        )
    )
    logger.info(
        "backfilled workflow inputs: %s += %s",
        saved.name,
        ", ".join(item.name for item in missing),
    )
