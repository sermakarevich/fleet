"""Run engine: turn a Flow plus inputs into launches (DESIGN.md §3.2, §3.4, §3.8).

Pure functions over the run store and the run directory (no subprocesses,
no asyncio) shared by the supervisor service and the CLI. ``start_run``
creates the run; ``advance`` moves ready steps toward launchable ``Launch``
values, folding finished step runs back into the run status.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from fleet.core.errors import TemplateError
from fleet.flows import graph
from fleet.flows.graph import Item
from fleet.flows.model import WHEN_FAILED, Flow, Step
from fleet.flows.templates import is_template, render, render_bool, render_mapping
from fleet.runs.run_dir import (
    NO_ITEM,
    create_run_dir,
    create_step_dir,
    new_run_id,
)
from fleet.runs.state import context, resolve_inputs
from fleet.runs.store import (
    FINISHED,
    Run,
    RunStatus,
    RunStore,
    StepRun,
    StepStatus,
)


@dataclass(frozen=True)
class Launch:
    """Everything the pool needs to execute one step run, all templates rendered."""

    step_run: StepRun
    step: Step
    kind: str  # coder | tool | human
    step_dir: Path
    attempt: int  # store.bump_attempt result
    prompt: str  # rendered (coder, human)
    tool: str | None  # tool steps
    args: dict[str, str]  # rendered tool args
    coder: str | None
    model: str | None
    cwd: Path
    isolation: str | None
    retries: int
    tools: tuple[str, ...]  # names for the prompt "Tools" section (coder steps)
    ctx: dict[str, Any]  # the template context used (for checks)


@dataclass(frozen=True)
class Advance:
    """One engine tick: fresh launches, fresh skips, and the final run status."""

    launches: tuple[Launch, ...]
    skipped: tuple[StepRun, ...]
    run_status: RunStatus | None  # set when the run just finished


def start_run(
    store: RunStore,
    fleet_home: Path,
    flow: Flow,
    given_inputs: Mapping[str, Any],
    now: datetime,
    *,
    start_key: str | None = None,
) -> Run:
    """Start a run: resolve inputs, freeze the flow file, insert rows.

    Raises FlowInvalid on a missing required input (via
    ``runs.state.resolve_inputs``). Creates the run dir (frozen flow.yaml
    copied from flow.source, inputs.json), inserts the Run row (status
    running) and one pending StepRun per step at NO_ITEM.
    """
    resolved = resolve_inputs(flow, given_inputs)
    run_id = new_run_id(now)
    now_iso = now.isoformat()
    target = create_run_dir(fleet_home, run_id, Path(flow.source), resolved)
    _ = target
    run = Run(
        id=run_id,
        flow=flow.name,
        status=RunStatus.running,
        inputs=resolved,
        started_at=now_iso,
        start_key=start_key,
    )
    store.create_run(run)
    store.add_step_runs(
        [
            StepRun(
                run_id=run_id,
                step=step.name,
                item_index=NO_ITEM,
                status=StepStatus.pending,
            )
            for step in flow.steps
        ]
    )
    return run


def advance(
    store: RunStore,
    flow: Flow,
    run: Run,
    run_dir: Path,
    now: datetime,
    *,
    defaults: Mapping[str, Any],
) -> Advance:
    """Move a run forward one tick, returning fresh launches and skips."""
    now_iso = now.isoformat()
    skipped = _promote_ready_steps(store, flow, run, run_dir, now_iso)
    _settle_dead_steps(store, flow, run, now_iso)
    _gate_item_steps(store, flow, run, run_dir, now_iso)
    launches = _launch_ready(store, flow, run, run_dir, now_iso, defaults)

    final_runs = store.step_runs(run.id)
    final_status, _ = _summarize(flow, final_runs)
    finished = graph.flow_status(final_status, [step.name for step in flow.steps])
    run_status: RunStatus | None = None
    if finished is not None:
        run_status = RunStatus(finished)
        store.finish_run(run.id, run_status, "", now_iso)
    return Advance(launches=tuple(launches), skipped=tuple(skipped), run_status=run_status)


def _promote_ready_steps(
    store: RunStore, flow: Flow, run: Run, run_dir: Path, now_iso: str
) -> list[StepRun]:
    """Mark newly ready steps skipped, expanded, or ready; return fresh skips."""
    step_runs = store.step_runs(run.id)
    step_status, started = _summarize(flow, step_runs)
    skipped: list[StepRun] = []
    for step in graph.ready_steps(flow, step_status, started):
        fresh = store.step_runs(run.id)
        ctx = context(flow, run, run_dir, fresh)
        if graph.skip(step, ctx):
            store.set_step_status(
                run.id, step.name, NO_ITEM, StepStatus.skipped, now_iso, "skip_if"
            )
            row = store.get_step_run(run.id, step.name, NO_ITEM)
            if row is not None:
                skipped.append(row)
        elif step.for_each is not None:
            _expand_step(store, run, step, ctx, now_iso)
        else:
            store.set_step_status(run.id, step.name, NO_ITEM, StepStatus.ready, now_iso)
    return skipped


def _settle_dead_steps(store: RunStore, flow: Flow, run: Run, now_iso: str) -> None:
    """Settle unreachable steps on their NO_ITEM row so the run can fold.

    A dead ``when: ok`` step becomes ``cancelled`` with reason
    ``need <name> <status>`` naming the first failed/cancelled need; a dead
    ``when: failed`` step becomes ``skipped`` with reason ``no need failed``.
    """
    step_status, started = _summarize(flow, store.step_runs(run.id))
    effective = dict(step_status)
    for step in graph.dead_steps(flow, step_status, started):
        if step.when == WHEN_FAILED:
            store.set_step_status(
                run.id, step.name, NO_ITEM, StepStatus.skipped, now_iso, "no need failed"
            )
            effective[step.name] = StepStatus.skipped.value
            continue
        reason = "no need failed"
        for need in step.needs:
            status = effective.get(need)
            if status in graph.FAILED:
                reason = f"need {need} {status}"
                break
        store.set_step_status(run.id, step.name, NO_ITEM, StepStatus.cancelled, now_iso, reason)
        effective[step.name] = StepStatus.cancelled.value


def _expand_step(
    store: RunStore, run: Run, step: Step, ctx: Mapping[str, Any], now_iso: str
) -> None:
    """Insert one pending row per for_each item; the NO_ITEM row runs the step."""
    try:
        items = graph.expand(step, ctx)
    except TemplateError as exc:
        store.set_step_status(run.id, step.name, NO_ITEM, StepStatus.failed, now_iso, str(exc))
        return
    store.add_step_runs(
        [
            StepRun(
                run_id=run.id,
                step=step.name,
                item_index=item.index,
                status=StepStatus.pending,
                key=item.key,
                after=item.after,
            )
            for item in items
        ]
    )
    store.set_step_status(run.id, step.name, NO_ITEM, StepStatus.running, now_iso)


def _gate_item_steps(store: RunStore, flow: Flow, run: Run, run_dir: Path, now_iso: str) -> None:
    """Move unblocked for_each items to ready; fold finished items into the summary."""
    for step in flow.steps:
        if step.for_each is None:
            continue
        summary = store.get_step_run(run.id, step.name, NO_ITEM)
        if summary is None or summary.status is not StepStatus.running:
            continue
        rows = store.step_runs(run.id)
        base_ctx = context(flow, run, run_dir, rows)
        item_rows = [row for row in rows if row.step == step.name and row.item_index != NO_ITEM]
        if not item_rows:
            continue
        try:
            parallel = render_bool(step.parallel, base_ctx)
        except TemplateError as exc:
            store.set_step_status(run.id, step.name, NO_ITEM, StepStatus.failed, now_iso, str(exc))
            continue
        ready = graph.ready_items(_stored_items(item_rows), _item_status(item_rows))
        if not parallel:
            busy = any(row.status is StepStatus.running for row in item_rows)
            ready = [] if busy else ready[:1]
        for item in ready:
            store.set_step_status(run.id, step.name, item.index, StepStatus.ready, now_iso)
        _fold_finished_items(store, run, step.name, now_iso)


def _stored_items(item_rows: list[StepRun]) -> list[Item]:
    """Rebuild graph Items from stored rows (values live only in templates)."""
    return [
        Item(
            index=row.item_index,
            value=None,
            key=row.key if row.key is not None else str(row.item_index),
            after=row.after,
        )
        for row in sorted(item_rows, key=lambda row: row.item_index)
    ]


def _item_status(item_rows: list[StepRun]) -> dict[str, str]:
    """Map stored item rows by key to their status string."""
    return {
        (row.key if row.key is not None else str(row.item_index)): row.status.value
        for row in item_rows
    }


def _fold_finished_items(store: RunStore, run: Run, step_name: str, now_iso: str) -> None:
    """Set a for_each summary row to the aggregate once every item finished."""
    current = [row for row in store.step_runs(run.id) if row.step == step_name]
    current_items = [row for row in current if row.item_index != NO_ITEM]
    if current_items and all(row.status in FINISHED for row in current_items):
        folded = graph.aggregate([row.status.value for row in current_items])
        if folded is not None:
            store.set_step_status(run.id, step_name, NO_ITEM, StepStatus(folded), now_iso)


def _launch_ready(
    store: RunStore,
    flow: Flow,
    run: Run,
    run_dir: Path,
    now_iso: str,
    defaults: Mapping[str, Any],
) -> list[Launch]:
    """Render every ready row of this run into a Launch, marking it running."""
    launches: list[Launch] = []
    rows = store.step_runs(run.id)
    base_ctx = context(flow, run, run_dir, rows)
    expansions: dict[str, list[Item] | TemplateError] = {}
    for row in store.ready_step_runs(limit=10_000):
        if row.run_id != run.id:
            continue
        step = flow.step(row.step)
        ctx = _launch_ctx(flow, run, run_dir, rows, base_ctx, expansions, step, row)
        if ctx is None:
            _fail_row(store, run, row, now_iso, expansions.get(step.name))
            continue
        try:
            launches.append(
                _render_launch(
                    store, merged_defaults(flow, defaults), run_dir, row, step, ctx, now_iso
                )
            )
        except (TemplateError, ValueError) as exc:
            store.set_step_status(
                run.id, row.step, row.item_index, StepStatus.failed, now_iso, str(exc)
            )
    return launches


def _launch_ctx(
    flow: Flow,
    run: Run,
    run_dir: Path,
    rows: list[StepRun],
    base_ctx: Mapping[str, Any],
    expansions: dict[str, list[Item] | TemplateError],
    step: Step,
    row: StepRun,
) -> dict[str, Any] | None:
    """Build one row's template context; None when its item cannot be resolved."""
    if row.item_index == NO_ITEM or step.for_each is None:
        return dict(base_ctx)
    if step.name not in expansions:
        try:
            expansions[step.name] = graph.expand(step, base_ctx)
        except TemplateError as exc:
            expansions[step.name] = exc
    expanded = expansions[step.name]
    if isinstance(expanded, TemplateError):
        return None
    match = next((item for item in expanded if item.index == row.item_index), None)
    if match is None:
        return None
    return dict(context(flow, run, run_dir, rows, item=match.value, index=match.index))


def _fail_row(
    store: RunStore,
    run: Run,
    row: StepRun,
    now_iso: str,
    expanded: list[Item] | TemplateError | None,
) -> None:
    """Mark a row failed when its for_each expansion (or item) is unusable."""
    if isinstance(expanded, TemplateError):
        reason = str(expanded)
    else:
        reason = f"no expanded item at index {row.item_index}"
    store.set_step_status(run.id, row.step, row.item_index, StepStatus.failed, now_iso, reason)


def merged_defaults(flow: Flow, defaults: Mapping[str, Any]) -> dict[str, Any]:
    """Merge caller defaults under the flow's own defaults (the flow wins)."""
    return {**defaults, **dict(flow.defaults)}


def finish_step_run(
    store: RunStore,
    step_run: StepRun,
    status: StepStatus,
    now: datetime,
    *,
    reason: str = "",
) -> None:
    """Record one step run's terminal status."""
    store.set_step_status(
        step_run.run_id, step_run.step, step_run.item_index, status, now.isoformat(), reason
    )


def cancel_run(store: RunStore, run: Run, now: datetime, reason: str) -> None:
    """Cancel a run: every non-finished step run and the run go to cancelled."""
    now_iso = now.isoformat()
    for row in store.step_runs(run.id):
        if row.status not in FINISHED:
            store.set_step_status(
                row.run_id, row.step, row.item_index, StepStatus.cancelled, now_iso, reason
            )
    store.finish_run(run.id, RunStatus.cancelled, reason, now_iso)


def retry_step_run(store: RunStore, step_run: StepRun, now: datetime, reason: str) -> None:
    """Send a step run back to ready; the next advance re-launches it."""
    store.set_step_status(
        step_run.run_id,
        step_run.step,
        step_run.item_index,
        StepStatus.ready,
        now.isoformat(),
        reason,
    )


def _summarize(flow: Flow, step_runs: list[StepRun]) -> tuple[dict[str, str], set[str]]:
    """Fold step rows into (name → status string, started names), as state.py does."""
    step_status: dict[str, str] = {}
    started: set[str] = set()
    for flow_step in flow.steps:
        matching = [row for row in step_runs if row.step == flow_step.name]
        if not matching:
            step_status[flow_step.name] = "pending"
            continue
        if any(row.status is not StepStatus.pending for row in matching):
            started.add(flow_step.name)
        item_rows = [row for row in matching if row.item_index != NO_ITEM]
        if item_rows:
            folded = graph.aggregate([row.status.value for row in item_rows])
            if folded is not None:
                step_status[flow_step.name] = folded
            elif any(row.status is StepStatus.running for row in item_rows):
                step_status[flow_step.name] = "running"
            else:
                step_status[flow_step.name] = "pending"
        else:
            step_status[flow_step.name] = matching[0].status.value
    return step_status, started


def _resolve_optional(
    step_value: str | None, field_name: str, ctx: Mapping[str, Any], merged: Mapping[str, Any]
) -> str | None:
    """Render an optional string field, falling back to merged defaults.

    An empty string after rendering means "unset" (None).
    """
    raw: Any = step_value if step_value is not None else merged.get(field_name)
    if raw is None:
        return None
    if isinstance(raw, str) and is_template(raw):
        raw = render(raw, ctx)
    if isinstance(raw, str):
        return raw if raw != "" else None
    text = str(raw)
    return text if text != "" else None


def _resolve_retries(
    step_value: int | str | None, ctx: Mapping[str, Any], merged: Mapping[str, Any]
) -> int:
    """Render the retries field, then int() it (unset means 0)."""
    raw: Any = step_value if step_value is not None else merged.get("retries", 0)
    if raw is None:
        return 0
    if isinstance(raw, bool):
        return int(raw)
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str):
        rendered = render(raw, ctx) if is_template(raw) else raw
        if rendered.strip() == "":
            return 0
        return int(rendered)
    return int(raw)


def _render_launch(
    store: RunStore,
    merged: Mapping[str, Any],
    run_dir: Path,
    row: StepRun,
    step: Step,
    ctx: Mapping[str, Any],
    now_iso: str,
) -> Launch:
    """Render one ready row into a Launch, marking it running.

    Raises TemplateError (or ValueError from a bad retries int) when a
    template cannot be rendered; the caller marks the row failed.
    """
    prompt = render(step.prompt, ctx)
    args = render_mapping(step.args, ctx)
    coder = _resolve_optional(step.coder, "coder", ctx, merged)
    model = _resolve_optional(step.model, "model", ctx, merged)
    cwd_text = _resolve_optional(step.cwd, "cwd", ctx, merged)
    isolation = _resolve_optional(step.isolation, "isolation", ctx, merged)
    retries = _resolve_retries(step.retries, ctx, merged)
    target = create_step_dir(run_dir, row.step, row.item_index)
    attempt = store.bump_attempt(row.run_id, row.step, row.item_index)
    store.set_step_status(row.run_id, row.step, row.item_index, StepStatus.running, now_iso)
    refreshed = store.get_step_run(row.run_id, row.step, row.item_index)
    current = refreshed if refreshed is not None else row
    return Launch(
        step_run=current,
        step=step,
        kind=step.kind,
        step_dir=target,
        attempt=attempt,
        prompt=prompt,
        tool=step.tool,
        args=args,
        coder=coder,
        model=model,
        cwd=Path(cwd_text) if cwd_text is not None else run_dir,
        isolation=isolation,
        retries=retries,
        tools=tuple(step.tools),
        ctx=dict(ctx),
    )
