"""The step that spawns the coder subprocess, streams stdout, classifies the exit.

This is the only step that talks to a model: it is the only place in the
worker layer that occupies a concurrency slot. Steps that wait or do pure
Python work take no slot — accounting for that stays in the orchestrator
(``rate_gauge`` / ``config.max_concurrent``), unchanged by this module.

Makes no queue calls: it returns a ``StepResult`` wrapping a
``TaskOutcomeRecord`` describing what happened (exit code, rate limit, kill
reason, ...) and leaves the caller (``orchestrator/reap.py``) to consult bead
status and drive the queue.
"""

from __future__ import annotations

import asyncio
import os
import signal
from datetime import UTC, datetime
from pathlib import Path

from fleet.core.limits import (
    PROBE_INTERVAL_SEC,
    PROBE_SILENCE_SEC,
    RATE_LIMIT_PROBE_SILENCE_SEC,
    SHUTDOWN_GRACE_SEC,
)
from fleet.core.task import TaskOutcome, TaskOutcomeRecord
from fleet.state.journal import append_event, open_task_log
from fleet.state.paths import RUN_JSON

from .base import StepContext, StepResult, write_run_json

_STDERR_TAIL_BYTES = 2048


def _signal_group(proc: asyncio.subprocess.Process, sig: int) -> None:
    """Signal the child's whole process group; fall back to the child alone."""
    try:
        os.killpg(os.getpgid(proc.pid), sig)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            proc.send_signal(sig)
        except (ProcessLookupError, OSError):
            pass


def _input_tokens(usage: dict) -> int:
    """Sum prompt-side tokens for context tracking; missing or non-int fields → 0."""

    def _int(v: object) -> int:
        return v if isinstance(v, int) and not isinstance(v, bool) else 0

    return (
        _int(usage.get("input_tokens"))
        + _int(usage.get("cache_creation_input_tokens"))
        + _int(usage.get("cache_read_input_tokens"))
    )


def _read_file_tail(path: Path, max_bytes: int = _STDERR_TAIL_BYTES) -> str | None:
    if not path.exists():
        return None
    with path.open("rb") as f:
        f.seek(0, 2)
        size = f.tell()
        f.seek(max(0, size - max_bytes))
        return f.read().decode("utf-8", errors="replace")


class LlmSession:
    """Spawn the coder subprocess for this attempt and turn its exit into an outcome."""

    name = "llm_session"

    def __init__(self) -> None:
        self._proc: asyncio.subprocess.Process | None = None
        self._cancelled = False
        self._killed = False
        self._kill_reason = "manual_kill"

    async def run(self, ctx: StepContext) -> StepResult:
        task = ctx.task
        coder = ctx.coder
        assert coder is not None
        task_dir = ctx.task_dir
        task_dir.mkdir(parents=True, exist_ok=True)
        attempt_dir = ctx.attempt_dir or task_dir
        attempt_dir.mkdir(parents=True, exist_ok=True)
        plan = ctx.scratch.get("launch_plan")
        launch_mode = plan.mode if plan is not None else "fresh"

        with open_task_log(attempt_dir, task.id) as task_log:
            stderr_path = Path(task_log.stderr_file.name)

            argv = coder.build_argv(task, task_dir, plan)
            extra_env = coder.env(task, task_dir)
            extra_env = {
                **extra_env,
                "FLEET_ATTEMPT_N": str(ctx.attempt_n),
                "FLEET_ATTEMPT_DIR": str(attempt_dir),
                "FLEET_LAUNCH_MODE": launch_mode,
            }
            proc_env = {**os.environ, **extra_env}
            if "BEADS_DIR" not in proc_env:
                proc_env["BEADS_DIR"] = str(ctx.fleet_home / ".beads")

            task_log.log.info(
                "subprocess_started",
                task_id=task.id,
                argv=argv,
            )

            proc = await asyncio.create_subprocess_exec(
                *argv,
                env=proc_env,
                cwd=ctx.project_root,
                stdout=asyncio.subprocess.PIPE,
                stderr=task_log.stderr_file,
                stdin=asyncio.subprocess.DEVNULL,
                start_new_session=True,
            )
            self._proc = proc
            started_at = datetime.now(tz=UTC)
            run_file = attempt_dir / RUN_JSON
            try:
                try:
                    pgid = os.getpgid(proc.pid)
                except OSError:
                    pgid = proc.pid
                write_run_json(
                    run_file,
                    pid=proc.pid,
                    pgid=pgid,
                    started_at=started_at.isoformat(),
                    coder=coder.__class__.__name__,
                )
            except OSError as exc:
                ctx.log.warning("run_file_write_failed", error=str(exc))

            # cancel() may have run while we were awaiting create_subprocess_exec
            # — at that moment `self._proc` was still None, so cancel() returned
            # without signalling. Close the race by sending SIGTERM here.
            if self._cancelled:
                _signal_group(proc, signal.SIGTERM)

            outcome: TaskOutcomeRecord | None = None
            peak_context_tokens: int = 0
            last_logged_bucket: int = -1
            _logged_session_started = False

            assert proc.stdout is not None
            # Default StreamReader limit is 64 KB; large MCP tool results (e.g. full
            # paper content or YouTube transcripts in a stream-json line) can exceed
            # even a generous limit and raise LimitOverrunError.  Use a manual
            # readline loop so we can catch and skip oversize lines instead of
            # crashing the whole runner.  In Python 3.12 the buffer IS consumed
            # before LimitOverrunError is raised, so `continue` is safe.
            proc.stdout._limit = 100 * 1024 * 1024
            last_event_at = started_at
            last_probe_at = started_at
            while True:
                try:
                    raw_bytes = await asyncio.wait_for(
                        proc.stdout.readline(), timeout=PROBE_INTERVAL_SEC
                    )
                except TimeoutError:
                    now = datetime.now(tz=UTC)
                    silent_for = (now - last_event_at).total_seconds()
                    since_last_probe = (now - last_probe_at).total_seconds()
                    if silent_for <= PROBE_SILENCE_SEC or since_last_probe < PROBE_INTERVAL_SEC:
                        continue
                    last_probe_at = now
                    probe_outcome = await asyncio.to_thread(
                        coder.probe_health, task, task_dir, last_event_at
                    )
                    if probe_outcome is None:
                        continue
                    if (
                        probe_outcome.outcome is TaskOutcome.RATE_LIMIT
                        and silent_for < RATE_LIMIT_PROBE_SILENCE_SEC
                    ):
                        # The CLI is still retrying the rate limit itself; give it time.
                        continue
                    task_log.log.warning(
                        "provider_error_detected",
                        task_id=task.id,
                        reason=probe_outcome.reason,
                    )
                    _signal_group(proc, signal.SIGTERM)
                    try:
                        await asyncio.wait_for(proc.wait(), timeout=5.0)
                    except TimeoutError:
                        _signal_group(proc, signal.SIGKILL)
                        await proc.wait()
                    outcome = probe_outcome
                    break
                except asyncio.LimitOverrunError as exc:
                    ctx.log.warning(
                        "stdout_line_overrun",
                        task_id=task.id,
                        consumed=exc.consumed,
                    )
                    continue
                if not raw_bytes:
                    break
                last_event_at = datetime.now(tz=UTC)
                raw_line = raw_bytes.decode("utf-8", errors="replace").rstrip("\n")
                evt = coder.normalize_event(raw_line)
                if evt is None:
                    continue

                append_event(attempt_dir, evt)

                if evt.kind == "session_started" and not _logged_session_started:
                    _logged_session_started = True
                    ctx.log.info("agent_session_started")
                elif evt.kind == "tool_use":
                    ctx.log.info(
                        "agent_tool_use",
                        tool=evt.tool_name
                        or evt.raw.get("tool_name")
                        or evt.raw.get("name"),
                    )
                elif evt.kind == "session_ended":
                    ctx.log.info("agent_session_ended")

                if evt.kind == "rate_limit_info":
                    ctx.rate_gauge.update(evt)
                elif evt.usage is not None and evt.kind != "session_ended":
                    prompt = _input_tokens(evt.usage)
                    if prompt > 0:
                        peak_context_tokens = max(peak_context_tokens, prompt)
                        pct = peak_context_tokens / coder.context_limit * 100
                        bucket = int(pct // 10)
                        if bucket > last_logged_bucket:
                            task_log.log.info(
                                "context_usage",
                                task_id=task.id,
                                context_tokens=peak_context_tokens,
                                context_limit=coder.context_limit,
                                pct=round(pct, 1),
                            )
                            last_logged_bucket = bucket

                if (
                    evt.kind == "rate_limit"
                    and evt.rate_info is not None
                    and evt.rate_info.get("status") == "rejected"
                ):
                    resets_at = evt.rate_info.get("resets_at")
                    reason = (
                        f"rate_limit, sleep until {resets_at}"
                        if resets_at is not None
                        else "rate_limit"
                    )
                    task_log.log.warning(
                        "rate_limit_rejected",
                        task_id=task.id,
                        resets_at=resets_at,
                    )
                    _signal_group(proc, signal.SIGTERM)
                    try:
                        await asyncio.wait_for(proc.wait(), timeout=5.0)
                    except TimeoutError:
                        _signal_group(proc, signal.SIGKILL)
                        await proc.wait()
                    outcome = TaskOutcomeRecord(
                        outcome=TaskOutcome.RATE_LIMIT,
                        exit_code=proc.returncode,
                        reason=reason,
                        resets_at=resets_at,
                    )
                    break

            exit_code = await proc.wait()
            try:
                write_run_json(
                    run_file,
                    exit_code=exit_code,
                    ended_at=datetime.now(tz=UTC).isoformat(),
                )
            except OSError as exc:
                ctx.log.warning("run_file_write_failed", error=str(exc))

            if outcome is None:
                cp_flag = task_dir / ".context_pressure"
                if cp_flag.exists():
                    cp_flag.unlink()
                    outcome = TaskOutcomeRecord(
                        outcome=TaskOutcome.CONTEXT_PRESSURE,
                        exit_code=exit_code,
                        reason="context_pressure hook fired",
                    )
                elif self._killed:
                    outcome = TaskOutcomeRecord(
                        outcome=TaskOutcome.KILLED,
                        exit_code=exit_code,
                        reason=self._kill_reason,
                    )
                elif self._cancelled:
                    outcome = TaskOutcomeRecord(
                        outcome=TaskOutcome.FAILURE,
                        exit_code=exit_code,
                        reason="supervisor_shutdown",
                    )
                elif exit_code == 0:
                    outcome = TaskOutcomeRecord(
                        outcome=TaskOutcome.SUCCESS,
                        exit_code=exit_code,
                        reason="",
                    )
                else:
                    stderr_tail = _read_file_tail(stderr_path)
                    outcome = TaskOutcomeRecord(
                        outcome=TaskOutcome.FAILURE,
                        exit_code=exit_code,
                        reason=f"subprocess exited with rc={exit_code}",
                        stderr_tail=stderr_tail,
                    )

            task_log.log.info(
                "subprocess_exited",
                task_id=task.id,
                exit_code=exit_code,
                outcome=outcome.outcome.value,
            )
            return StepResult(status="outcome", outcome=outcome)

    async def cancel(self, reason: str) -> None:
        """Signal the child's process group; escalate to SIGKILL after grace period.

        ``reason == "supervisor_shutdown"`` marks the run as a shutdown
        (-> FAILURE); any other reason marks it as a manual/stall kill
        (-> KILLED with that reason).
        """
        if reason == "supervisor_shutdown":
            self._cancelled = True
        else:
            self._killed = True
            self._kill_reason = reason
        proc = self._proc
        if proc is None or proc.returncode is not None:
            return
        _signal_group(proc, signal.SIGTERM)
        try:
            await asyncio.wait_for(
                proc.wait(),
                timeout=float(SHUTDOWN_GRACE_SEC),
            )
        except TimeoutError:
            _signal_group(proc, signal.SIGKILL)
            await proc.wait()
