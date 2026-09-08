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
import socket
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fleet.core.limits import (
    HEARTBEAT_SEC,
    PROBE_INTERVAL_SEC,
    PROBE_SILENCE_SEC,
    RATE_LIMIT_PROBE_SILENCE_SEC,
    SHUTDOWN_GRACE_SEC,
)
from fleet.core.task import TaskOutcome, TaskOutcomeRecord
from fleet.state.journal import append_event, open_task_log
from fleet.state.paths import CHECKPOINT_REQUESTED_MARKER, RUN_JSON

from .base import StepContext, StepResult, write_run_json

_STDERR_TAIL_BYTES = 2048

# Substrings (case-insensitive) of the CLIs' own "context is full" errors.
# When stderr or an event carries one, the session is over even if usage
# counters never crossed the kill threshold.
_CONTEXT_ERROR_PATTERNS = (
    "prompt is too long",
    "context length",
    "maximum context",
    "context window",
    "token limit",
    "too many tokens",
    "input is too long",
    "context too large",
    "exceeds the context",
    "exceed context",
)


def context_limit_of(coder, overrides: dict[str, int] | None = None) -> int:
    """Effective context window for this coder/model pair.

    Prefers the ``context_limit_for(model, overrides)`` classmethod
    (per-model table from ``core.context_window``); falls back to the
    ``context_limit`` attribute for test doubles. *overrides* is the parsed
    ``context_windows`` config (``{model: tokens}``); None means built-ins.
    """
    try:
        return int(coder.context_limit_for(getattr(coder, "model", None), overrides))
    except (AttributeError, TypeError, ValueError):
        pass
    try:
        return int(coder.context_limit)
    except (AttributeError, TypeError, ValueError):
        return 200_000


def overrides_of(config) -> dict[str, int]:
    """Parse ``config.context_windows`` into ``{model: tokens}``.

    A malformed value must never kill a session: it parses to {} (built-in
    table only) so the checkpoint/kill thresholds keep a sane denominator.
    """
    from fleet.core.context_window import parse_context_windows

    raw = getattr(config, "context_windows", "") or ""
    try:
        return parse_context_windows(raw)
    except ValueError:
        return {}


def is_context_error_text(text: str) -> bool:
    """True when *text* looks like a CLI context-overflow error."""
    lowered = text.lower()
    return any(pat in lowered for pat in _CONTEXT_ERROR_PATTERNS)


def error_text_of(evt) -> str:
    """The error payload of *evt*, or "" when the event carries no error.

    Only ``error`` events and the error fields of a ``session_ended`` event
    count. The model's own prose (``assistant_text``) is never scanned: a
    worker that *talks about* "context windows" is not overflowing one.
    """
    import json as _json

    raw = evt.raw if isinstance(evt.raw, dict) else {}
    if evt.kind == "error":
        candidate = raw
    elif evt.kind == "session_ended":
        candidate = {k: raw[k] for k in ("error", "errors", "message") if raw.get(k)}
        if raw.get("is_error") and raw.get("result"):
            candidate["result"] = raw["result"]
    else:
        return ""
    if not candidate:
        return ""
    try:
        return _json.dumps(candidate)[:8000]
    except (TypeError, ValueError):
        return ""


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


def _max_attempt_sec(ctx) -> float | None:
    """Per-attempt wall-clock ceiling in seconds, or None when disabled.

    Per-task override (bd metadata fleet_max_attempt_minutes) wins over the
    global RuntimeConfig.max_attempt_minutes. 0 (or negative) means off.
    """
    raw = ctx.task.max_attempt_minutes
    if raw is None:
        raw = ctx.config.max_attempt_minutes
    try:
        minutes = int(raw)
    except (TypeError, ValueError):
        return None
    if minutes <= 0:
        return None
    return float(minutes * 60)


def _read_file_tail(path: Path, max_bytes: int = _STDERR_TAIL_BYTES) -> str | None:
    if not path.exists():
        return None
    with path.open("rb") as f:
        f.seek(0, 2)
        size = f.tell()
        f.seek(max(0, size - max_bytes))
        return f.read().decode("utf-8", errors="replace")


def _host_name() -> str:
    """This machine's hostname for the run.json lease (best effort)."""
    try:
        return socket.gethostname()
    except OSError:
        return "unknown"


def _lease_times(now: datetime | None = None) -> tuple[str, str]:
    """Return (heartbeat_at, lease_until) ISO timestamps for *now*.

    The lease outlives one heartbeat by 3x so a single slow event-loop
    tick can never make it look expired.
    """
    at = now or datetime.now(tz=UTC)
    return at.isoformat(), (at + timedelta(seconds=3 * HEARTBEAT_SEC)).isoformat()


async def _heartbeat_loop(run_file: Path, proc: asyncio.subprocess.Process) -> None:
    """Refresh heartbeat_at/lease_until in run.json until cancelled.

    Also exits on its own once the subprocess is gone, so an unexpected
    exception in the readout loop can never leave a heartbeat refreshing
    a dead attempt's lease forever. Read-merge-write (via write_run_json)
    so the heartbeat never clobbers keys other writers own (pid, steps,
    exit_code). A failed write is skipped: the lease simply ages, which
    is the safe direction.
    """
    try:
        while proc.returncode is None:
            await asyncio.sleep(float(HEARTBEAT_SEC))
            if proc.returncode is not None:
                break
            heartbeat_at, lease_until = _lease_times()
            try:
                write_run_json(
                    run_file,
                    heartbeat_at=heartbeat_at,
                    lease_until=lease_until,
                )
            except OSError:
                pass
    except asyncio.CancelledError:
        pass


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
                    host=_host_name(),
                    supervisor_pid=os.getpid(),
                    heartbeat_at=started_at.isoformat(),
                    lease_until=_lease_times(started_at)[1],
                )
            except OSError as exc:
                ctx.log.warning("run_file_write_failed", error=str(exc))

            heartbeat_task = asyncio.create_task(_heartbeat_loop(run_file, proc))

            # cancel() may have run while we were awaiting create_subprocess_exec
            # — at that moment `self._proc` was still None, so cancel() returned
            # without signalling. Close the race by sending SIGTERM here.
            if self._cancelled:
                _signal_group(proc, signal.SIGTERM)

            outcome: TaskOutcomeRecord | None = None
            peak_context_tokens: int = 0
            last_logged_bucket: int = -1
            _logged_session_started = False
            context_limit = context_limit_of(coder, overrides_of(ctx.config))
            checkpoint_pct = ctx.config.context_checkpoint_pct
            kill_pct = ctx.config.context_kill_pct
            checkpoint_file = attempt_dir / CHECKPOINT_REQUESTED_MARKER
            checkpoint_written = checkpoint_file.exists()

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
            attempt_budget_sec = _max_attempt_sec(ctx)
            while True:
                try:
                    raw_bytes = await asyncio.wait_for(
                        proc.stdout.readline(), timeout=PROBE_INTERVAL_SEC
                    )
                except TimeoutError:
                    now = datetime.now(tz=UTC)
                    if (
                        attempt_budget_sec is not None
                        and (now - started_at).total_seconds() > attempt_budget_sec
                    ):
                        task_log.log.warning(
                            "attempt_timeout",
                            task_id=task.id,
                            budget_sec=int(attempt_budget_sec),
                        )
                        _signal_group(proc, signal.SIGTERM)
                        try:
                            await asyncio.wait_for(proc.wait(), timeout=5.0)
                        except TimeoutError:
                            _signal_group(proc, signal.SIGKILL)
                            await proc.wait()
                        outcome = TaskOutcomeRecord(
                            outcome=TaskOutcome.KILLED,
                            exit_code=proc.returncode,
                            reason="timeout",
                        )
                        break
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
                if (
                    attempt_budget_sec is not None
                    and (last_event_at - started_at).total_seconds() > attempt_budget_sec
                ):
                    task_log.log.warning(
                        "attempt_timeout",
                        task_id=task.id,
                        budget_sec=int(attempt_budget_sec),
                    )
                    _signal_group(proc, signal.SIGTERM)
                    try:
                        await asyncio.wait_for(proc.wait(), timeout=5.0)
                    except TimeoutError:
                        _signal_group(proc, signal.SIGKILL)
                        await proc.wait()
                    outcome = TaskOutcomeRecord(
                        outcome=TaskOutcome.KILLED,
                        exit_code=proc.returncode,
                        reason="timeout",
                    )
                    break
                raw_line = raw_bytes.decode("utf-8", errors="replace").rstrip("\n")
                evt = coder.normalize_event(raw_line)
                if evt is None:
                    continue
                if evt.session_id:
                    # Lets probe_health tell this run's provider errors apart
                    # from other sessions sharing the same CLI log file.
                    coder.current_session_id = evt.session_id

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
                        pct = peak_context_tokens / context_limit * 100
                        bucket = int(pct // 10)
                        if bucket > last_logged_bucket:
                            task_log.log.info(
                                "context_usage",
                                task_id=task.id,
                                context_tokens=peak_context_tokens,
                                context_limit=context_limit,
                                pct=round(pct, 1),
                            )
                            last_logged_bucket = bucket
                        if pct >= checkpoint_pct and not checkpoint_written:
                            try:
                                checkpoint_file.touch(exist_ok=True)
                            except OSError as exc:
                                ctx.log.warning(
                                    "checkpoint_marker_failed", error=str(exc)
                                )
                            checkpoint_written = True
                            task_log.log.warning(
                                "context_checkpoint",
                                task_id=task.id,
                                pct=round(pct, 1),
                            )
                        if pct >= kill_pct:
                            task_log.log.warning(
                                "context_kill",
                                task_id=task.id,
                                pct=round(pct, 1),
                            )
                            _signal_group(proc, signal.SIGTERM)
                            try:
                                await asyncio.wait_for(proc.wait(), timeout=5.0)
                            except TimeoutError:
                                _signal_group(proc, signal.SIGKILL)
                                await proc.wait()
                            outcome = TaskOutcomeRecord(
                                outcome=TaskOutcome.CONTEXT_PRESSURE,
                                exit_code=proc.returncode,
                                reason=(
                                    f"context limit {pct:.1f}% >= kill {kill_pct}% "
                                    f"({peak_context_tokens}/{context_limit} tokens)"
                                ),
                            )
                            break

                if evt.kind in ("error", "session_ended"):
                    searchable = error_text_of(evt)
                    if searchable and is_context_error_text(searchable):
                        task_log.log.warning(
                            "context_overflow_reported",
                            task_id=task.id,
                            kind=evt.kind,
                        )
                        _signal_group(proc, signal.SIGTERM)
                        try:
                            await asyncio.wait_for(proc.wait(), timeout=5.0)
                        except TimeoutError:
                            _signal_group(proc, signal.SIGKILL)
                            await proc.wait()
                        outcome = TaskOutcomeRecord(
                            outcome=TaskOutcome.CONTEXT_PRESSURE,
                            exit_code=proc.returncode,
                            reason="cli reported context overflow",
                        )
                        break

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
            heartbeat_task.cancel()
            await asyncio.gather(heartbeat_task, return_exceptions=True)
            try:
                write_run_json(
                    run_file,
                    exit_code=exit_code,
                    ended_at=datetime.now(tz=UTC).isoformat(),
                    peak_context_tokens=peak_context_tokens,
                )
            except OSError as exc:
                ctx.log.warning("run_file_write_failed", error=str(exc))

            if outcome is None:
                if self._killed:
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
                    if stderr_tail is not None and is_context_error_text(stderr_tail):
                        outcome = TaskOutcomeRecord(
                            outcome=TaskOutcome.CONTEXT_PRESSURE,
                            exit_code=exit_code,
                            reason="cli reported context overflow",
                            stderr_tail=stderr_tail,
                        )
                    else:
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
        _signal_group(proc, signal.SIGTERM)
        try:
            await asyncio.wait_for(
                proc.wait(),
                timeout=float(SHUTDOWN_GRACE_SEC),
            )
        except TimeoutError:
            _signal_group(proc, signal.SIGKILL)
            await proc.wait()
