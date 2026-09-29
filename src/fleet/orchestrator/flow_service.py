"""Supervisor flow service: advance runs, launch steps, reap them (DESIGN.md §3.6).

The periodic ``flows`` service (``ServiceOrder.Flows``, between Claim and
Reap) ties the run engine to the pool: each tick it reaps finished coder /
tool / human step runs, settles them (after-checks, retry / fail / skip /
stop), then advances every running run and dispatches fresh launches
(before-checks first, then a coder worker, tool task, or human task).

Capped coder launches are NOT set back to ready: the engine already bumped
their attempt, so re-rendering would double-count. Instead the ``Launch`` is
held in ``FlowState.waiting`` (its row stays ``running``) and dispatched
first on the next tick.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

from fleet.core.config import RuntimeConfig
from fleet.core.errors import FlowInvalid, FlowNotFound
from fleet.flows.folders import Catalog, load_catalog
from fleet.flows.model import Check, Flow, effective_checks
from fleet.flows.templates import render
from fleet.orchestrator.claim import can_claim
from fleet.orchestrator.flow_coder import (
    FlowWorker,
    coder_outcome,
    copy_declared_outputs,
    start_coder_step,
    step_task_id,
)
from fleet.orchestrator.service import PeriodicService, ServiceOrder
from fleet.orchestrator.starts import StartClock, due_cron, parse_every, poll_tool_start
from fleet.pool.checks import Verdict, decide, retry_feedback, run_checks
from fleet.pool.human_run import ask_human, write_human_outputs
from fleet.pool.tool_run import run_tool, write_step_outputs
from fleet.runs import engine
from fleet.runs import run_dir as run_paths
from fleet.runs.engine import Launch, cancel_run, finish_step_run, retry_step_run
from fleet.runs.store import Run, RunStatus, RunStore, StepStatus, runs_db_path

if TYPE_CHECKING:
    from fleet.orchestrator.state import SupervisorState


@dataclass
class FlowState:
    """One per SupervisorState: the catalog, run store, and in-flight steps."""

    catalog: Catalog
    store: RunStore
    coders: dict[str, FlowWorker]  # key: step run task id
    tools: dict[str, asyncio.Task[tuple[bool, str]]]  # tool steps in flight, same key
    humans: dict[str, asyncio.Task[tuple[bool, str]]]  # human steps in flight, same key
    waiting: list[Launch] = field(default_factory=list)  # capped coder launches
    feedback: dict[str, str] = field(default_factory=dict)  # check retry text, by task id
    pending: dict[str, tuple[Launch, str]] = field(default_factory=dict)  # tool/human ctx
    starts: StartClock = field(default_factory=StartClock)  # last cron fire / tool poll


def _defaults(config: RuntimeConfig) -> dict[str, Any]:
    """Engine defaults from the real RuntimeConfig fields.

    RuntimeConfig has no default_cwd or max-attempts field, so those keys
    are left out: the engine falls back to the run dir for cwd and 0 for
    retries (flow ``defaults`` / step ``retries`` override via
    ``merged_defaults``).
    """
    return {
        "coder": config.coder,
        "model": config.model,
        "isolation": config.isolation,
        "retries": 0,
    }


async def on_start(st: SupervisorState) -> None:
    """Load the catalog, open the run store, and recover orphaned running steps."""
    catalog = load_catalog(st.config)
    for problem in catalog.problems:
        st.log.warning("flow_catalog_problem", problem=problem)
    st.flows = FlowState(
        catalog=catalog,
        store=RunStore(runs_db_path(st.fleet_home)),
        coders={},
        tools={},
        humans={},
        starts=StartClock(),
    )
    recovered = engine.recover_running_steps(st.flows.store, st.clock.now())
    for row in recovered:
        st.log.info(
            "flow_steps_recovered",
            run_id=row.run_id,
            step=row.step,
            item=row.item_index,
            attempt=row.attempt,
        )


async def on_stop(st: SupervisorState) -> None:
    """Cancel in-flight step work; rows left running are recovered by the next on_start."""
    fs = cast(FlowState | None, st.flows)
    if fs is None:
        return
    for worker in fs.coders.values():
        with contextlib.suppress(Exception):
            await worker.run.cancel()
        worker.future.cancel()
    for task in (*fs.tools.values(), *fs.humans.values()):
        task.cancel()


async def tick(st: SupervisorState) -> None:
    """Start due flows, then reap finished steps, dispatch held launches, advance runs."""
    fs = cast(FlowState | None, st.flows)
    if fs is None or st.shutting_down:
        return
    await _run_starts(st, fs)
    await _reap_coders(st, fs)
    await _reap_tasks(st, fs, fs.tools, "tool")
    await _reap_tasks(st, fs, fs.humans, "human")
    await _dispatch_waiting(st, fs)
    await _advance_runs(st, fs)


_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


async def _run_starts(st: SupervisorState, fs: FlowState) -> None:
    """Step 0: for every enabled flow, fire due cron starts and due tool polls."""
    now = st.clock.now()
    for flow in fs.catalog.flows.values():
        if not flow.enabled:
            continue
        if flow.on.cron is not None:
            try:
                due = due_cron(flow, fs.starts.cron_last.get(flow.name), now)
            except Exception as exc:  # noqa: BLE001 - a bad expr skips until next due
                st.log.warning("start_cron_invalid", flow=flow.name, reason=str(exc))
                fs.starts.cron_last[flow.name] = now
                due = False
            if due:
                try:
                    engine.start_run(fs.store, st.fleet_home, flow, {}, now)
                except FlowInvalid as exc:
                    st.log.warning("start_cron_invalid", flow=flow.name, reason=str(exc))
                fs.starts.cron_last[flow.name] = now
        if flow.on.tool is not None:
            try:
                interval = parse_every(flow.on.tool.every)
            except ValueError as exc:
                st.log.warning("start_tool_bad_every", flow=flow.name, reason=str(exc))
                continue
            last_poll = fs.starts.tool_last.get(flow.name, _EPOCH)
            if (now - last_poll).total_seconds() < interval:
                continue
            try:
                tool = fs.catalog.tool(flow.on.tool.name)
            except Exception:  # noqa: BLE001 - KeyError/FlowNotFound both mean unknown
                st.log.warning("start_tool_unknown", flow=flow.name, tool=flow.on.tool.name)
                continue
            await poll_tool_start(
                flow,
                tool,
                fs.store,
                st.fleet_home,
                now,
                environ=os.environ,
                log=st.log,
            )
            fs.starts.tool_last[flow.name] = now


async def _reap_coders(st: SupervisorState, fs: FlowState) -> None:
    """Settle every coder step run whose future is done."""
    for task_id, worker in list(fs.coders.items()):
        if not worker.future.done():
            continue
        del fs.coders[task_id]
        try:
            ok, reason = coder_outcome(worker)
        except asyncio.CancelledError:
            ok, reason = False, "cancelled"
        await settle(st, fs, worker.launch, worker.run_id, ok, reason)


async def _reap_tasks(
    st: SupervisorState,
    fs: FlowState,
    mapping: dict[str, asyncio.Task[tuple[bool, str]]],
    kind: str,
) -> None:
    """Settle every done tool/human task; its result is ``(ok, reason)``."""
    for task_id, task in list(mapping.items()):
        if not task.done():
            continue
        del mapping[task_id]
        pending = fs.pending.pop(task_id, None)
        try:
            ok, reason = task.result()
        except asyncio.CancelledError:
            ok, reason = False, "cancelled"
        except Exception as exc:  # noqa: BLE001 - a step bug must not kill the tick
            ok, reason = False, str(exc) or type(exc).__name__
        if pending is None:
            st.log.warning("flow_orphan_step", task_id=task_id, kind=kind)
            continue
        launch, run_id = pending
        await settle(st, fs, launch, run_id, ok, reason)


async def _dispatch_waiting(st: SupervisorState, fs: FlowState) -> None:
    """Dispatch held coder launches first; still-capped ones are held again."""
    if not fs.waiting:
        return
    held = fs.waiting
    fs.waiting = []
    for launch in held:
        run = fs.store.get_run(launch.step_run.run_id)
        if run is None or run.status is not RunStatus.running:
            continue
        try:
            flow = fs.catalog.flow(run.flow)
        except FlowNotFound:
            continue  # _advance_runs cancels runs whose flow vanished
        await dispatch(st, fs, flow, run, launch)


async def _advance_runs(st: SupervisorState, fs: FlowState) -> None:
    """Advance every running run; a missing flow cancels its run."""
    now = st.clock.now()
    for run in fs.store.list_runs(status=RunStatus.running):
        try:
            flow = fs.catalog.flow(run.flow)
        except FlowNotFound:
            cancel_run(fs.store, run, now, "flow no longer in catalog")
            st.log.warning("flow_missing", run_id=run.id, flow=run.flow)
            continue
        adv = engine.advance(
            fs.store,
            flow,
            run,
            run_paths.run_dir(st.fleet_home, run.id),
            now,
            defaults=_defaults(st.config),
        )
        for launch in adv.launches:
            await dispatch(st, fs, flow, run, launch)
        if adv.run_status is not None:
            st.log.info("run_finished", run_id=run.id, flow=run.flow, status=adv.run_status.value)


async def dispatch(
    st: SupervisorState, fs: FlowState, flow: Flow, run: Run, launch: Launch
) -> None:
    """Run before-checks, then start the step as a coder worker / tool / human task."""
    now = st.clock.now()
    task_id = step_task_id(launch, run)
    attempt_dir = run_paths.attempt_dir(launch.step_dir, launch.attempt)
    before = await run_checks(
        effective_checks(flow, launch.step),
        launch.ctx,
        when="before",
        tools=fs.catalog.tool,
        cwd=launch.cwd,
        attempt_dir=attempt_dir,
        environ=os.environ,
        ask_store=st.question_store,
        task_id=task_id,
        run_coder_check=_coder_check_runner(st, launch, run),
    )
    if not before.ok:
        assert before.failed is not None
        verdict = before.verdicts[-1]
        if before.failed.on_fail == "skip":
            finish_step_run(
                fs.store, launch.step_run, StepStatus.skipped, now, reason=verdict.message
            )
        elif before.failed.on_fail == "stop":
            cancel_run(fs.store, run, now, verdict.message)
        else:  # fail, and retry (nothing to retry yet: no attempt ran)
            finish_step_run(
                fs.store,
                launch.step_run,
                StepStatus.failed,
                now,
                reason=f"before check {before.failed.name}: {verdict.message}",
            )
        st.log.info(
            "flow_before_check_failed",
            run_id=run.id,
            step=launch.step_run.step,
            check=before.failed.name,
            fate=before.failed.on_fail,
        )
        return
    if launch.kind == "coder":
        if not can_claim(st, launch.coder):
            fs.waiting.append(launch)
            return
        try:
            worker = start_coder_step(st, launch, run, fs.feedback.pop(task_id, ""))
        except Exception as exc:  # noqa: BLE001 - a bad launch fails the step, not the tick
            finish_step_run(fs.store, launch.step_run, StepStatus.failed, now, reason=str(exc))
            return
        fs.coders[task_id] = worker
    elif launch.kind == "tool":
        fs.pending[task_id] = (launch, run.id)
        fs.tools[task_id] = asyncio.create_task(
            _run_tool_step(fs.catalog.tool, launch), name=f"flow-tool:{task_id}"
        )
    elif launch.kind == "human":
        fs.pending[task_id] = (launch, run.id)
        context = _reuse_human_context(st.question_store, task_id, launch.attempt)
        fs.humans[task_id] = asyncio.create_task(
            _run_human_step(st.question_store, launch, task_id, context),
            name=f"flow-human:{task_id}",
        )
    else:
        finish_step_run(
            fs.store,
            launch.step_run,
            StepStatus.failed,
            now,
            reason=f"unknown step kind {launch.kind}",
        )


async def _run_tool_step(lookup: Any, launch: Launch) -> tuple[bool, str]:
    """Run one tool step: execute, publish outputs when ok, return ``(ok, reason)``."""
    try:
        tool = lookup(launch.tool or "")
    except Exception:  # noqa: BLE001 - KeyError/FlowNotFound both mean "no such tool"
        return False, f"unknown tool {launch.tool}"
    try:
        result = await run_tool(
            tool,
            launch.args,
            cwd=launch.cwd,
            attempt_dir=run_paths.attempt_dir(launch.step_dir, launch.attempt),
            environ=os.environ,
        )
    except Exception as exc:  # noqa: BLE001 - a spawn failure fails the step, not the tick
        return False, str(exc) or type(exc).__name__
    if result.ok:
        write_step_outputs(launch.step_dir, result.output)
    return result.ok, (result.stderr or "")


async def _run_human_step(
    question_store: Any, launch: Launch, task_id: str, context: str
) -> tuple[bool, str]:
    """Ask one human question, publish the answer, return ``(ok, reason)``.

    ``context`` comes from :func:`_reuse_human_context`: a re-launched
    attempt reuses the previous attempt's still-pending question for the
    same task id instead of asking twice. Answered rows from the previous
    attempt are ignored (their answer never reached ``outputs.json``, or
    the step would have finished); :func:`ask_human` still returns a
    stored answer when the reused question resolves first.
    """
    if question_store is None:
        return False, "no question store"
    try:
        answer = await ask_human(
            question_store,
            launch.prompt,
            task_id=task_id,
            context=context,
        )
    except Exception as exc:  # noqa: BLE001 - an ask failure fails the step, not the tick
        return False, str(exc) or type(exc).__name__
    write_human_outputs(launch.step_dir, answer)
    if answer.cancelled:
        return False, "cancelled"
    return True, ""


def _reuse_human_context(question_store: Any, task_id: str, attempt: int) -> str:
    """Ask context for a human launch, reusing a still-pending question.

    Returns the oldest pending question's context for ``task_id`` so the
    relaunch waits on it instead of asking twice; otherwise
    ``f"step:{attempt}"``. Runs synchronously inside ``dispatch`` so the
    decision is settled before the step task starts (nothing can answer
    in between and cause a duplicate question).
    """
    fetch = getattr(question_store, "fetch_pending_for_task", None)
    if fetch is not None:
        try:
            pending = fetch(task_id)
        except Exception:  # noqa: BLE001 - a store hiccup falls back to a fresh ask
            pending = []
        if pending:
            prev = _pending_context(pending[0])
            if prev:
                return prev
    return f"step:{attempt}"


def _pending_context(row: Any) -> str | None:
    """Read the ``context`` off a pending question row (mapping or attribute)."""
    getter = getattr(row, "get", None)
    value = getter("context") if callable(getter) else getattr(row, "context", None)
    return value if isinstance(value, str) and value else None


async def settle(
    st: SupervisorState, fs: FlowState, launch: Launch, run_id: str, ok: bool, reason: str
) -> None:
    """Fold a finished step run into the store: after-checks, then retry/finish."""
    now = st.clock.now()
    run = fs.store.get_run(run_id)
    if run is None:
        st.log.warning("flow_run_missing", run_id=run_id)
        return
    task_id = step_task_id(launch, run)
    attempt_dir = run_paths.attempt_dir(launch.step_dir, launch.attempt)
    if ok:
        try:
            flow = fs.catalog.flow(run.flow)
        except FlowNotFound:
            cancel_run(fs.store, run, now, "flow no longer in catalog")
            return
        ctx = {**launch.ctx, "outputs": run_paths.read_outputs(launch.step_dir)}
        outcome = await run_checks(
            effective_checks(flow, launch.step),
            ctx,
            when="after",
            tools=fs.catalog.tool,
            cwd=launch.cwd,
            attempt_dir=attempt_dir,
            environ=os.environ,
            ask_store=st.question_store,
            task_id=task_id,
            run_coder_check=_coder_check_runner(st, launch, run),
        )
        fate = decide(outcome, attempt=launch.attempt, retries=launch.retries)
        if fate == "pass":
            finish_step_run(fs.store, launch.step_run, StepStatus.succeeded, now)
        elif fate == "retry":
            verdict = outcome.verdicts[-1]
            retry_step_run(fs.store, launch.step_run, now, reason=verdict.message)
            fs.feedback[task_id] = retry_feedback(verdict)
        elif fate == "fail":
            verdict = outcome.verdicts[-1]
            finish_step_run(
                fs.store, launch.step_run, StepStatus.failed, now, reason=verdict.message
            )
        elif fate == "skip":
            verdict = outcome.verdicts[-1]
            finish_step_run(
                fs.store, launch.step_run, StepStatus.skipped, now, reason=verdict.message
            )
        else:  # stop
            verdict = outcome.verdicts[-1]
            cancel_run(fs.store, run, now, verdict.message)
        st.log.info(
            "flow_step_settled",
            run_id=run.id,
            step=launch.step_run.step,
            fate=fate,
            attempt=launch.attempt,
        )
        return
    if launch.attempt <= launch.retries:
        retry_step_run(fs.store, launch.step_run, now, reason=reason)
    else:
        finish_step_run(fs.store, launch.step_run, StepStatus.failed, now, reason=reason)


def _coder_check_runner(st: SupervisorState, launch: Launch, run: Run):  # noqa: ANN202
    """Build the coder-check runner over one step run's launch.

    Launches a one-shot coder whose prompt is the check prompt rendered over
    the check context and whose step dir is
    ``attempt_dir/checks/<name>/``, awaits it, and reads
    ``outputs.json`` ``{ok, message}`` into a Verdict. Blocks the tick while
    it runs; a later bead can make it concurrent.
    """

    async def _run(check: Check, ctx: Mapping[str, Any]) -> Verdict:
        check_dir = run_paths.attempt_dir(launch.step_dir, launch.attempt) / "checks" / check.name
        try:
            check_launch = replace(
                launch,
                prompt=render(check.prompt, ctx),
                step_dir=check_dir,
                attempt=1,
                coder=check.coder or launch.coder,
                model=check.model or launch.model,
            )
            worker = start_coder_step(st, check_launch, run)
        except Exception as exc:  # noqa: BLE001 - a bad checker fails the check, not the tick
            return Verdict(name=check.name, ok=False, message=str(exc), kind=check.kind)
        try:
            record = await worker.future
        except Exception as exc:  # noqa: BLE001 - a crashed checker fails the check
            return Verdict(
                name=check.name, ok=False, message=f"checker failed: {exc}", kind=check.kind
            )
        _ = record
        copy_declared_outputs(check_dir, worker.attempt_dir)
        outputs = run_paths.read_outputs(check_dir)
        if not outputs:
            return Verdict(
                name=check.name, ok=False, message="checker wrote no outputs", kind=check.kind
            )
        return Verdict(
            name=check.name,
            ok=outputs.get("ok") is True,
            message=str(outputs.get("message", "")),
            outputs=outputs,
            kind=check.kind,
        )

    return _run


def make_flow_service(interval_sec: float = 5.0) -> PeriodicService:
    """Build the supervisor flow service (ticks every ``interval_sec``)."""
    return PeriodicService(
        name="flows",
        order=ServiceOrder.Flows,
        interval_sec=interval_sec,
        tick=tick,
        on_start=on_start,
        on_stop=on_stop,
    )
