"""Run template context (docs/27_sep_upgrade/DESIGN.md §3.2 "Templates", §3.4).

Builds the Jinja context templates render over: resolved run inputs plus
every step's outputs read from the run directory on disk.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from fleet.core.errors import FlowInvalid
from fleet.flows.graph import aggregate
from fleet.flows.model import Flow
from fleet.flows.templates import Context
from fleet.runs.run_dir import NO_ITEM, read_outputs, read_verdicts, step_dir
from fleet.runs.store import Run, StepRun, StepStatus


def resolve_inputs(flow: Flow, given: Mapping[str, Any]) -> dict[str, Any]:
    """Resolve run inputs against the flow's declared inputs.

    Values given by the caller win; declared inputs with a default fill in
    when absent. Raises FlowInvalid naming every missing required input
    (``input <name>: required``) and every undeclared name
    (``input <name>: unknown``). Values are kept as given, never coerced.
    """
    declared = {item.name: item for item in flow.inputs}
    problems = [f"input {name}: unknown" for name in given if name not in declared]
    problems.extend(
        f"input {item.name}: required"
        for item in flow.inputs
        if item.required and item.name not in given
    )
    if problems:
        raise FlowInvalid(problems)
    resolved: dict[str, Any] = {}
    for item in flow.inputs:
        if item.name in given:
            resolved[item.name] = given[item.name]
        elif item.default is not None:
            resolved[item.name] = item.default
    return resolved


def context(
    flow: Flow,
    run: Run,
    run_dir: Path,
    step_runs: Sequence[StepRun],
    item: Any = None,
    index: int | None = None,
    outputs: Mapping[str, Any] | None = None,
) -> Context:
    """Build the template context for a run (DESIGN.md §3.2, §3.4).

    Keys: ``inputs`` (resolved run inputs), ``run`` (id, date, flow),
    ``defaults`` (flow defaults), ``steps`` (per step: ``outputs`` for the
    NO_ITEM step run or {} when there is none, ``items`` per-item outputs
    ordered by item index, ``status`` aggregated via
    ``flows.graph.aggregate`` or the NO_ITEM row's status, ``checks`` the
    latest attempt's check verdicts of the NO_ITEM step dir, ``item_checks``
    the per-item verdicts ordered like ``items``), ``item``/``index`` (only
    when ``index`` is given, for ``for_each`` step templates), ``outputs``
    (only when the ``outputs`` argument is given, the step's fresh outputs
    for check templates).
    """
    steps: dict[str, dict[str, Any]] = {}
    for flow_step in flow.steps:
        matching = [entry for entry in step_runs if entry.step == flow_step.name]
        if any(entry.item_index == NO_ITEM for entry in matching):
            step_outputs = read_outputs(step_dir(run_dir, flow_step.name))
        else:
            step_outputs = {}
        ordered = sorted(
            (entry for entry in matching if entry.item_index != NO_ITEM),
            key=lambda entry: entry.item_index,
        )
        items = [
            read_outputs(step_dir(run_dir, flow_step.name, entry.item_index)) for entry in ordered
        ]
        item_checks = [
            read_verdicts(step_dir(run_dir, flow_step.name, entry.item_index)) for entry in ordered
        ]
        steps[flow_step.name] = {
            "outputs": step_outputs,
            "items": items,
            "status": _step_status(matching),
            "checks": read_verdicts(step_dir(run_dir, flow_step.name)),
            "item_checks": item_checks,
        }
    result: dict[str, Any] = {
        "inputs": resolve_inputs(flow, run.inputs),
        "run": {"id": run.id, "date": run.started_at[:10], "flow": run.flow},
        "defaults": dict(flow.defaults),
        "steps": steps,
    }
    if index is not None:
        result["item"] = item
        result["index"] = index
    if outputs is not None:
        result["outputs"] = dict(outputs)
    return result


def _step_status(matching: Sequence[StepRun]) -> str:
    """Fold matching step rows into one template status string."""
    if not matching:
        return "pending"
    item_rows = [entry for entry in matching if entry.item_index != NO_ITEM]
    rows = item_rows or matching
    if item_rows:
        folded = aggregate([entry.status.value for entry in rows])
        if folded:
            return folded
        if any(entry.status is StepStatus.running for entry in rows):
            return "running"
        return "pending"
    return rows[0].status.value
