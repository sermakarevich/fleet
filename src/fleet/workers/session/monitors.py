"""Ordered session monitors: one check each, one level of abstraction.

Each :class:`Monitor` watches a running coder session through
:meth:`Monitor.on_event` (one streamed event) and :meth:`Monitor.on_tick`
(time-based state, every :data:`MONITOR_TICK_SEC`). The first monitor to
return a :class:`Verdict` with ``kill=True`` ends the session; the shared
:class:`MonitorContext` holds the mutable run facts. Monitors run sorted by
``order``, like the supervisor services in ADR 0005. Callers are
``workers/llm_session.py`` (``run_monitored`` via :func:`build_monitors``);
unit tests drive each monitor with synthetic events and no subprocess.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from structlog import BoundLogger

from fleet.coders.base import FALLBACK_CONTEXT_LIMIT, Coder, context_limit_for
from fleet.core.clock import Clock, SystemClock
from fleet.core.config import RuntimeConfig
from fleet.core.context_window import parse_context_windows
from fleet.core.limits import (
    HEARTBEAT_SEC,
    PROBE_INTERVAL_SEC,
    PROBE_SILENCE_SEC,
    RATE_LIMIT_PROBE_SILENCE_SEC,
)
from fleet.core.task import Event, EventKind, Task, TaskOutcome
from fleet.state.paths import CHECKPOINT_REQUESTED_MARKER
from fleet.state.run_file import RunRecord

from ..base import RateGaugeLike, StepContext
from .classify import error_text_of, is_context_error_text

# Tick cadence for on_tick: the existing probe interval, not a new one.
MONITOR_TICK_SEC = PROBE_INTERVAL_SEC


@dataclass(frozen=True)
class Verdict:
    """One monitor's decision: the outcome and whether the process must die."""

    outcome: TaskOutcome
    reason: str = ""
    kill: bool = True
    resets_at: int | None = None


@dataclass
class MonitorContext:
    """Mutable facts shared by one monitored run; owned by run_monitored."""

    task: Task
    task_dir: Path
    attempt_dir: Path
    coder: Coder
    config: RuntimeConfig
    rate_gauge: RateGaugeLike
    task_log: BoundLogger
    ctx_log: BoundLogger
    context_limit: int
    checkpoint_pct: int
    kill_pct: int
    attempt_budget_sec: float | None
    started_at: datetime
    last_event_at: datetime
    last_stdout_at: datetime
    last_probe_at: datetime
    clock: Clock
    session_id: str | None = None
    verdict: Verdict | None = None
    peak_context_tokens: int = 0
    last_logged_bucket: int = -1
    checkpoint_written: bool = False
    session_started_logged: bool = False


class Monitor:
    """One check over a running session; override on_event and/or on_tick."""

    order: int = 100

    def on_event(self, event: Event, ctx: MonitorContext) -> Verdict | None:
        """Inspect one streamed event; return a Verdict to end the session."""
        return None

    def on_tick(
        self, now: datetime, ctx: MonitorContext
    ) -> Verdict | None | Awaitable[Verdict | None]:
        """Inspect time-based state; may be async when the check does I/O."""
        return None


class SessionEventLogger(Monitor):
    """One-line ctx logs for session start, tool use, and session end."""

    order = 5

    def on_event(self, event: Event, ctx: MonitorContext) -> Verdict | None:
        if event.kind == EventKind.SESSION_STARTED:
            if not ctx.session_started_logged:
                ctx.session_started_logged = True
                ctx.ctx_log.info("agent_session_started")
        elif event.kind == EventKind.TOOL_USE:
            ctx.ctx_log.info(
                "agent_tool_use",
                tool=event.tool_name or event.raw.get("tool_name") or event.raw.get("name"),
            )
        elif event.kind == EventKind.SESSION_ENDED:
            ctx.ctx_log.info("agent_session_ended")
        return None


class RateGaugeFeeder(Monitor):
    """Feeds rate-limit info events into the orchestrator's rate gauge."""

    order = 10

    def on_event(self, event: Event, ctx: MonitorContext) -> Verdict | None:
        if event.kind == EventKind.RATE_LIMIT_INFO:
            ctx.rate_gauge.update(event)
        return None


class AttemptBudget(Monitor):
    """Kills the session past its wall-clock budget (-> KILLED/timeout)."""

    order = 15

    def on_event(self, event: Event, ctx: MonitorContext) -> Verdict | None:
        return self._check(ctx.clock.now(), ctx)

    def on_tick(self, now: datetime, ctx: MonitorContext) -> Verdict | None:
        return self._check(now, ctx)

    def _check(self, now: datetime, ctx: MonitorContext) -> Verdict | None:
        """Verdict when *now* is past the attempt ceiling, else None."""
        if ctx.attempt_budget_sec is None:
            return None
        if (now - ctx.started_at).total_seconds() <= ctx.attempt_budget_sec:
            return None
        ctx.task_log.warning(
            "attempt_timeout",
            task_id=ctx.task.id,
            budget_sec=int(ctx.attempt_budget_sec),
        )
        return Verdict(TaskOutcome.KILLED, "timeout")


class ContextGauge(Monitor):
    """Tracks input tokens; checkpoints at checkpoint pct, kills at kill pct."""

    order = 20

    def on_event(self, event: Event, ctx: MonitorContext) -> Verdict | None:
        if (
            event.kind == EventKind.RATE_LIMIT_INFO
            or event.usage is None
            or event.kind == EventKind.SESSION_ENDED
        ):
            return None
        prompt = _input_tokens(event.usage)
        if prompt <= 0:
            return None
        ctx.peak_context_tokens = max(ctx.peak_context_tokens, prompt)
        pct = ctx.peak_context_tokens / ctx.context_limit * 100
        bucket = int(pct // 10)
        if bucket > ctx.last_logged_bucket:
            ctx.last_logged_bucket = bucket
            ctx.task_log.info(
                "context_usage",
                task_id=ctx.task.id,
                context_tokens=ctx.peak_context_tokens,
                context_limit=ctx.context_limit,
                pct=round(pct, 1),
            )
        if pct >= ctx.checkpoint_pct and not ctx.checkpoint_written:
            try:
                (ctx.attempt_dir / CHECKPOINT_REQUESTED_MARKER).touch(exist_ok=True)
            except OSError as exc:
                ctx.ctx_log.warning("checkpoint_marker_failed", error=str(exc))
            ctx.checkpoint_written = True
            ctx.task_log.warning("context_checkpoint", task_id=ctx.task.id, pct=round(pct, 1))
        if pct >= ctx.kill_pct:
            ctx.task_log.warning("context_kill", task_id=ctx.task.id, pct=round(pct, 1))
            return Verdict(
                TaskOutcome.CONTEXT_PRESSURE,
                f"context limit {pct:.1f}% >= kill {ctx.kill_pct}% "
                f"({ctx.peak_context_tokens}/{ctx.context_limit} tokens)",
            )
        return None


class ContextErrorScanner(Monitor):
    """Kills the session when the CLI itself reports a context overflow."""

    order = 30

    def on_event(self, event: Event, ctx: MonitorContext) -> Verdict | None:
        if event.kind not in (EventKind.ERROR, EventKind.SESSION_ENDED):
            return None
        searchable = error_text_of(event)
        if searchable and is_context_error_text(searchable):
            ctx.task_log.warning(
                "context_overflow_reported",
                task_id=ctx.task.id,
                kind=event.kind,
            )
            return Verdict(TaskOutcome.CONTEXT_PRESSURE, "cli reported context overflow")
        return None


class HealthProbe(Monitor):
    """Kills silent sessions whose provider reports an error or rate limit."""

    order = 40

    def on_event(self, event: Event, ctx: MonitorContext) -> Verdict | None:
        if (
            event.kind != EventKind.RATE_LIMIT
            or event.rate_info is None
            or event.rate_info.get("status") != "rejected"
        ):
            return None
        resets_at = event.rate_info.get("resets_at")
        reason = f"rate_limit, sleep until {resets_at}" if resets_at is not None else "rate_limit"
        ctx.task_log.warning(
            "rate_limit_rejected",
            task_id=ctx.task.id,
            resets_at=resets_at,
        )
        return Verdict(TaskOutcome.RATE_LIMIT, reason, resets_at=resets_at)

    async def on_tick(self, now: datetime, ctx: MonitorContext) -> Verdict | None:
        silent_for = (now - ctx.last_stdout_at).total_seconds()
        if (
            silent_for <= PROBE_SILENCE_SEC
            or (now - ctx.last_probe_at).total_seconds() < MONITOR_TICK_SEC
        ):
            return None
        ctx.last_probe_at = now
        probe = getattr(ctx.coder, "probe_health", None)
        if probe is None:
            return None
        probe_outcome = await asyncio.to_thread(
            probe, ctx.task, ctx.task_dir, ctx.last_stdout_at, ctx.session_id
        )
        if probe_outcome is None:
            return None
        if (
            probe_outcome.outcome is TaskOutcome.RATE_LIMIT
            and silent_for < RATE_LIMIT_PROBE_SILENCE_SEC
        ):
            # The CLI is still retrying the rate limit itself; give it time.
            return None
        ctx.task_log.warning(
            "provider_error_detected",
            task_id=ctx.task.id,
            reason=probe_outcome.reason,
        )
        return Verdict(
            probe_outcome.outcome,
            probe_outcome.reason,
            resets_at=probe_outcome.resets_at,
        )


class LeaseHeartbeat(Monitor):
    """Refreshes heartbeat_at/lease_until in run.json while the session runs."""

    order = 90

    def on_tick(self, now: datetime, ctx: MonitorContext) -> Verdict | None:
        heartbeat_at, lease_until = lease_times(now)
        with contextlib.suppress(OSError):
            RunRecord.touch_lease(ctx.attempt_dir, lease_until, heartbeat_at)
        return None


def lease_times(now: datetime | None = None) -> tuple[str, str]:
    """Return (heartbeat_at, lease_until) ISO timestamps for *now*.

    The lease outlives one heartbeat by 3x so a single slow event-loop
    tick can never make it look expired.
    """
    at = now or datetime.now(tz=UTC)
    return at.isoformat(), (at + timedelta(seconds=3 * HEARTBEAT_SEC)).isoformat()


def context_limit_of(coder: Coder, overrides: dict[str, int] | None = None) -> int:
    """Effective context window for this coder/model pair.

    Resolves through the shared ``context_limit_for`` table from the coder's
    spec; test doubles without a spec fall back to their ``context_limit``
    attribute. *overrides* is the parsed ``context_windows`` config
    (``{model: tokens}``); None means built-ins.
    """
    spec = getattr(coder, "spec", None)
    if spec is None:
        limit = getattr(coder, "context_limit", None)
        try:
            return int(limit) if limit is not None else FALLBACK_CONTEXT_LIMIT
        except (TypeError, ValueError):
            return FALLBACK_CONTEXT_LIMIT
    try:
        return context_limit_for(spec, getattr(coder, "model", None), overrides)
    except (TypeError, ValueError):
        return spec.context_limit


def overrides_of(config: RuntimeConfig) -> dict[str, int]:
    """Parse ``config.context_windows`` into ``{model: tokens}``.

    A malformed value must never kill a session: it parses to {} (built-in
    table only) so the checkpoint/kill thresholds keep a sane denominator.
    """
    raw = getattr(config, "context_windows", "") or ""
    try:
        return parse_context_windows(raw)
    except ValueError:
        return {}


def _max_attempt_sec(step: StepContext) -> float | None:
    """Per-attempt wall-clock ceiling in seconds, or None when disabled.

    Per-task override (bd metadata fleet_max_attempt_minutes) wins over the
    global RuntimeConfig.max_attempt_minutes. 0 (or negative) means off.
    """
    raw = step.task.max_attempt_minutes
    if raw is None:
        raw = step.config.max_attempt_minutes
    try:
        minutes = int(raw)
    except (TypeError, ValueError):
        return None
    if minutes <= 0:
        return None
    return float(minutes * 60)


def _input_tokens(usage: dict) -> int:
    """Sum prompt-side tokens for context tracking; missing fields count 0."""

    def _int(value: object) -> int:
        return value if isinstance(value, int) and not isinstance(value, bool) else 0

    return (
        _int(usage.get("input_tokens"))
        + _int(usage.get("cache_creation_input_tokens"))
        + _int(usage.get("cache_read_input_tokens"))
    )


def build_monitors(
    step: StepContext, task_log: BoundLogger, attempt_dir: Path
) -> tuple[list[Monitor], MonitorContext]:
    """Create the ordered monitors and their shared context for one run."""
    assert step.coder is not None
    clock: Clock = step.clock or SystemClock()
    started_at = clock.now()
    ctx = MonitorContext(
        task=step.task,
        task_dir=step.task_dir,
        attempt_dir=attempt_dir,
        coder=step.coder,
        config=step.config,
        rate_gauge=step.rate_gauge,
        task_log=task_log,
        ctx_log=step.log,
        context_limit=context_limit_of(step.coder, overrides_of(step.config)),
        checkpoint_pct=step.config.context_checkpoint_pct,
        kill_pct=step.config.context_kill_pct,
        attempt_budget_sec=_max_attempt_sec(step),
        started_at=started_at,
        last_event_at=started_at,
        last_stdout_at=started_at,
        last_probe_at=started_at,
        clock=clock,
        checkpoint_written=(attempt_dir / CHECKPOINT_REQUESTED_MARKER).exists(),
    )
    monitors: list[Monitor] = [
        SessionEventLogger(),
        RateGaugeFeeder(),
        AttemptBudget(),
        ContextGauge(),
        ContextErrorScanner(),
        HealthProbe(),
        LeaseHeartbeat(),
    ]
    return (sorted(monitors, key=lambda monitor: monitor.order), ctx)
