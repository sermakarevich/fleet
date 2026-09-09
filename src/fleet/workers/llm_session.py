"""The step that spawns the coder subprocess, streams stdout, classifies the exit.

This is the only step that talks to a model: it is the only place in the
worker layer that occupies a concurrency slot. Steps that wait or do pure
Python work take no slot — accounting for that stays in the orchestrator
(``rate_gauge`` / ``config.max_concurrent``), unchanged by this module.

Makes no queue calls: it returns a ``StepResult`` wrapping a
``TaskOutcomeRecord`` describing what happened (exit code, rate limit, kill
reason, ...) and leaves the caller (``orchestrator/reap.py``) to consult bead
status and drive the queue.

The run is split per ADR 0006: ``session/process.py`` owns the subprocess,
``session/stream.py`` the event feed, ``session/monitors.py`` the policy
checks, ``session/classify.py`` the exit table. This module only wires them.
"""

from __future__ import annotations

import asyncio
import inspect
import os
import signal
from datetime import UTC, datetime
from pathlib import Path

from fleet.core.iso import now_iso
from fleet.core.launch_policy import LaunchPlan
from fleet.core.limits import SHUTDOWN_GRACE_SEC
from fleet.core.process import host_name
from fleet.core.task import Event, TaskOutcomeRecord
from fleet.state.atomic import write_text_atomic
from fleet.state.journal import TaskLogRecord, open_task_log
from fleet.state.paths import PROMPT_MD, RUN_JSON

from .base import StepContext, StepResult, StepStatus, write_run_json
from .session import monitors as monitors_mod
from .session.classify import classify_exit
from .session.monitors import (
    Monitor,
    MonitorContext,
    Verdict,
    build_monitors,
    lease_times,
)
from .session.process import KILL_GRACE_SEC, CoderProcess
from .session.stream import EventStream


def _record_of(verdict: Verdict, exit_code: int | None) -> TaskOutcomeRecord:
    """Fill a monitor verdict with the reaped exit code."""
    return TaskOutcomeRecord(
        outcome=verdict.outcome,
        exit_code=exit_code,
        reason=verdict.reason,
        resets_at=verdict.resets_at,
    )


def _event_verdict(monitors: list[Monitor], event: Event, state: MonitorContext) -> Verdict | None:
    """First verdict from the monitors for one event, or None."""
    for monitor in monitors:
        verdict = monitor.on_event(event, state)
        if verdict is not None:
            return verdict
    return None


async def _tick_loop(proc: CoderProcess, monitors: list[Monitor], state: MonitorContext) -> None:
    """Call every monitor's on_tick each tick; a kill verdict ends the session."""
    while True:
        # Read off the monitors module (not a local binding) so the cadence
        # stays the single MONITOR_TICK_SEC owned there.
        await asyncio.sleep(float(monitors_mod.MONITOR_TICK_SEC))
        now = datetime.now(tz=UTC)
        for monitor in monitors:
            verdict = monitor.on_tick(now, state)
            if inspect.isawaitable(verdict):
                verdict = await verdict
            if verdict is not None and verdict.kill:
                if state.verdict is None:
                    state.verdict = verdict
                await proc.terminate_group(KILL_GRACE_SEC)
                return


async def run_monitored(
    proc: CoderProcess,
    stream: EventStream,
    monitors: list[Monitor],
    state: MonitorContext,
) -> TaskOutcomeRecord | None:
    """Stream events through monitors with a tick task; return a kill record."""
    tick = asyncio.create_task(_tick_loop(proc, monitors, state))
    try:
        async for evt in stream:
            state.last_event_at = stream.last_event_at
            state.last_stdout_at = stream.last_stdout_at
            if stream.last_session_id is not None:
                state.session_id = stream.last_session_id
            verdict = _event_verdict(monitors, evt, state)
            if verdict is not None and verdict.kill:
                await proc.terminate_group(KILL_GRACE_SEC)
                await proc.wait()
                return _record_of(verdict, proc.returncode)
        await proc.wait()
        if state.verdict is not None:
            return _record_of(state.verdict, proc.returncode)
        return None
    finally:
        tick.cancel()
        await asyncio.gather(tick, return_exceptions=True)


def _spawn_env(
    ctx: StepContext, task_dir: Path, attempt_dir: Path, launch_mode: str
) -> dict[str, str]:
    """Attempt env layered over the coder env: FLEET_* plus BEADS_DIR."""
    coder = ctx.coder
    assert coder is not None
    proc_env = {
        **os.environ,
        **coder.env(ctx.task, task_dir),
        "FLEET_ATTEMPT_N": str(ctx.attempt_n),
        "FLEET_ATTEMPT_DIR": str(attempt_dir),
        "FLEET_LAUNCH_MODE": launch_mode,
    }
    if "BEADS_DIR" not in proc_env:
        proc_env["BEADS_DIR"] = str(ctx.fleet_home / ".beads")
    return proc_env


class LlmSession:
    """Spawn the coder subprocess for this attempt and turn its exit into an outcome."""

    name = "llm_session"

    def __init__(self) -> None:
        self._proc: CoderProcess | None = None
        self._cancelled = False
        self._killed = False
        self._kill_reason = "manual_kill"

    async def run(self, ctx: StepContext) -> StepResult:
        """Spawn the coder, stream it through the monitors, classify the exit."""
        task = ctx.task
        coder = ctx.coder
        assert coder is not None
        task_dir = ctx.task_dir
        task_dir.mkdir(parents=True, exist_ok=True)
        attempt_dir = ctx.attempt_dir or task_dir
        attempt_dir.mkdir(parents=True, exist_ok=True)
        plan = ctx.plan if ctx.plan is not None else ctx.launch_plan
        launch_mode = plan.mode if plan is not None else "fresh"
        with open_task_log(attempt_dir, task.id) as task_log:
            await self._spawn(ctx, task_dir, attempt_dir, task_log, plan, launch_mode)
            proc = self._proc
            assert proc is not None
            if self._cancelled:
                proc.signal_group(signal.SIGTERM)
            monitors, state = build_monitors(ctx, task_log.log, attempt_dir)
            stream = EventStream(
                proc,
                coder,
                attempt_dir=attempt_dir,
                started_at=state.started_at,
                stderr_path=Path(task_log.stderr_file.name),
                log=ctx.log,
                task_id=task.id,
            )
            verdict = await run_monitored(proc, stream, monitors, state)
            exit_code = await proc.wait()
            outcome = classify_exit(
                exit_code,
                verdict=verdict,
                killed=self._killed,
                kill_reason=self._kill_reason,
                cancelled=self._cancelled,
                stderr_tail=stream.stderr_tail,
            )
            self._finish(ctx, task_log, attempt_dir, state, exit_code, outcome)
            return StepResult(status=StepStatus.OUTCOME, outcome=outcome)

    async def _spawn(
        self,
        ctx: StepContext,
        task_dir: Path,
        attempt_dir: Path,
        task_log: TaskLogRecord,
        plan: LaunchPlan | None,
        launch_mode: str,
    ) -> None:
        """Build argv/env, start the coder process, record pid and prompt."""
        coder = ctx.coder
        assert coder is not None
        argv = coder.build_argv(ctx.task, task_dir, plan)
        # Record the exact prompt sent (coders always put it last) so
        # debugging and prompt tuning never have to fish it out of logs.
        try:
            write_text_atomic(attempt_dir / PROMPT_MD, argv[-1] if argv else "")
        except OSError as exc:
            ctx.log.warning("prompt_write_failed", error=str(exc))
        proc_env = _spawn_env(ctx, task_dir, attempt_dir, launch_mode)
        task_log.log.info(
            "subprocess_started",
            task_id=ctx.task.id,
            # The prompt text lives in attempts/<n>/prompt.md; the
            # log line keeps the argv shape but stays small.
            argv=[*argv[:-1], "<see prompt.md>"] if argv else [],
        )
        proc = await CoderProcess.start(argv, proc_env, ctx.workdir, stderr=task_log.stderr_file)
        self._proc = proc
        started_at = datetime.now(tz=UTC)
        try:
            write_run_json(
                attempt_dir / RUN_JSON,
                pid=proc.pid,
                pgid=proc.pgid,
                started_at=started_at.isoformat(),
                coder=coder.__class__.__name__,
                host=host_name(),
                supervisor_pid=os.getpid(),
                heartbeat_at=started_at.isoformat(),
                lease_until=lease_times(started_at)[1],
            )
        except OSError as exc:
            ctx.log.warning("run_file_write_failed", error=str(exc))

    def _finish(
        self,
        ctx: StepContext,
        task_log: TaskLogRecord,
        attempt_dir: Path,
        state: MonitorContext,
        exit_code: int | None,
        outcome: TaskOutcomeRecord,
    ) -> None:
        """Record exit metrics and the subprocess_exited log line."""
        try:
            write_run_json(
                attempt_dir / RUN_JSON,
                exit_code=exit_code,
                ended_at=now_iso(),
                peak_context_tokens=state.peak_context_tokens,
            )
        except OSError as exc:
            ctx.log.warning("run_file_write_failed", error=str(exc))
        task_log.log.info(
            "subprocess_exited",
            task_id=ctx.task.id,
            exit_code=exit_code,
            outcome=outcome.outcome.value,
        )

    async def cancel(self, reason: str) -> None:
        """Signal the child's process group; escalate to SIGKILL after grace period.

        ``reason == "supervisor_shutdown"`` marks the run as a shutdown
        (-> FAILURE with that reason, which core/retry_policy re-queues at
        once without counting a round); any other reason marks it as a
        manual/stall kill (-> KILLED with that reason).
        """
        if reason == "supervisor_shutdown":
            self._cancelled = True
        else:
            self._killed = True
            self._kill_reason = reason
        proc = self._proc
        if proc is None or proc.returncode is not None:
            return
        await proc.terminate_group(float(SHUTDOWN_GRACE_SEC))
