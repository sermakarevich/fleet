"""Flow graph readiness: which steps and for_each items may run (DESIGN.md §3.2, §3.4).

Pure functions over a :class:`fleet.flows.model.Flow` plus current statuses.
Statuses are plain strings matching ``fleet.runs.store.StepStatus`` values,
kept as strings here so ``flows`` never imports ``runs``.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from fleet.core.errors import TemplateError
from fleet.flows.model import Flow, Step
from fleet.flows.templates import render, render_bool, render_value

FINISHED: frozenset[str] = frozenset({"succeeded", "failed", "skipped", "cancelled"})
"""Statuses after which a step or item never runs again."""

OK: frozenset[str] = frozenset({"succeeded", "skipped"})
"""Statuses whose dependents may proceed; failed/cancelled block forever."""


@dataclass(frozen=True)
class Item:
    """One expanded ``for_each`` element with its resolved key and waits."""

    index: int
    value: Any
    key: str
    after: tuple[str, ...] = ()


def ready_steps(flow: Flow, step_status: Mapping[str, str], started: Collection[str]) -> list[Step]:
    """Return steps not in ``started`` whose every need has status in OK.

    Flow order is preserved. A need that is missing, unfinished, failed or
    cancelled keeps the step unready; failed/cancelled never become OK.
    """
    ready: list[Step] = []
    for flow_step in flow.steps:
        if flow_step.name in started:
            continue
        if all(step_status.get(need) in OK for need in flow_step.needs):
            ready.append(flow_step)
    return ready


def expand(step: Step, ctx: Mapping[str, Any]) -> list[Item]:
    """Expand ``step.for_each`` into items with rendered keys and waits.

    Raises ValueError when the step has no ``for_each`` and TemplateError
    when the list, a key, or an ``after`` entry cannot be resolved (duplicate
    keys and ``after`` names without a matching key included).
    """
    if step.for_each is None:
        raise ValueError(f"step {step.name}: for_each is required to expand items")
    raw_items = render_value(step.for_each, ctx)
    if not isinstance(raw_items, list):
        raise TemplateError(
            f"cannot expand for_each for step {step.name}: expected a list, got {raw_items!r}"
        )
    items: list[Item] = []
    seen: set[str] = set()
    for position, element in enumerate(raw_items):
        item_ctx = {**ctx, "item": element, "index": position}
        item_key = render(step.key, item_ctx) if step.key is not None else str(position)
        if item_key in seen:
            raise TemplateError(
                f"cannot expand for_each for step {step.name}: duplicate key {item_key!r}"
            )
        seen.add(item_key)
        items.append(
            Item(
                index=position,
                value=element,
                key=item_key,
                after=tuple(_render_after(step, item_ctx)),
            )
        )
    known = {item.key for item in items}
    for item in items:
        for dependency in item.after:
            if dependency not in known:
                raise TemplateError(
                    f"cannot expand for_each for step {step.name}: unknown after key {dependency!r}"
                )
    if not render_bool(step.parallel, ctx):
        return [
            Item(
                index=item.index,
                value=item.value,
                key=item.key,
                after=item.after + (() if item.index == 0 else (items[item.index - 1].key,)),
            )
            for item in items
        ]
    return items


def _render_after(step: Step, item_ctx: Mapping[str, Any]) -> list[str]:
    """Render ``step.after`` over one item's context into a list of keys."""
    if step.after is None:
        return []
    rendered = render_value(step.after, item_ctx)
    if isinstance(rendered, str):
        return [rendered]
    if isinstance(rendered, (list, tuple)):
        names: list[str] = []
        for entry in rendered:
            if not isinstance(entry, str):
                raise TemplateError(
                    f"cannot expand for_each for step {step.name}: "
                    f"after entries must be strings, got {entry!r}"
                )
            names.append(entry)
        return names
    raise TemplateError(
        f"cannot expand for_each for step {step.name}: "
        f"after must be a string or a list, got {rendered!r}"
    )


def ready_items(items: Sequence[Item], item_status: Mapping[str, str]) -> list[Item]:
    """Return pending items whose every ``after`` key has status in OK."""
    ready: list[Item] = []
    for item in items:
        if item_status.get(item.key, "pending") != "pending":
            continue
        if all(item_status.get(dependency) in OK for dependency in item.after):
            ready.append(item)
    return ready


def aggregate(statuses: Collection[str]) -> str | None:
    """Fold finished statuses; None when empty or any status is unfinished."""
    collected = list(statuses)
    if not collected or any(status not in FINISHED for status in collected):
        return None
    if any(status == "failed" for status in collected):
        return "failed"
    if any(status == "cancelled" for status in collected):
        return "cancelled"
    return "succeeded"


def flow_status(step_status: Mapping[str, str], all_steps: Collection[str]) -> str | None:
    """Fold a whole flow; None while any step is missing or unfinished."""
    names = list(all_steps)
    if any(name not in step_status for name in names):
        return None
    return aggregate([step_status[name] for name in names])


def skip(step: Step, ctx: Mapping[str, Any]) -> bool:
    """Return True when ``step.skip_if`` renders true; False when unset."""
    if step.skip_if is None:
        return False
    return render_bool(step.skip_if, ctx)
