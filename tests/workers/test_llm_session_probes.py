"""Tests for LlmSession health/rate-limit monitors (unit under test: workers/session monitors)."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import structlog

from fleet.core.clock import FakeClock
from fleet.core.config import RuntimeConfig
from fleet.core.limits import PROBE_SILENCE_SEC, RATE_LIMIT_PROBE_SILENCE_SEC
from fleet.core.task import Task, TaskOutcome, TaskOutcomeRecord
from fleet.state.paths import task_dir
from fleet.workers.base import StepContext
from fleet.workers.llm_session import LlmSession
from fleet.workers.session.monitors import HealthProbe, MonitorContext
from fleet.workers.session.process import SubprocessRunner
from tests.workers.conftest import StubCoder, StubRateGauge, _make_session, _run
from tests.workers.fake_runner import FakeProcess, FakeProcessRunner


class _ProbeCoder(StubCoder):
    def __init__(self, outcome: TaskOutcomeRecord) -> None:
        super().__init__(argv=[sys.executable, "-c", "pass"])
        self._outcome = outcome
        self.probe_calls = 0

    def probe_health(self, task, task_dir, since, session_id=None):
        self.probe_calls += 1
        return self._outcome


def _fast_forward_ctx(
    tmp_path: Path, task: Task, coder, runner: FakeProcessRunner, *, tick_sec: float = 10.0
) -> tuple[StepContext, FakeClock]:
    """Session context where sleeps advance a fake clock (no real waiting)."""
    clock = FakeClock(start=datetime.now(tz=UTC))

    async def _sleep(sec: float) -> None:
        clock.advance(sec)
        await asyncio.sleep(0)

    return (
        StepContext(
            task=task,
            task_dir=task_dir(tmp_path, task.id),
            workdir=tmp_path,
            fleet_home=tmp_path,
            coder=coder,
            config=RuntimeConfig(),
            rate_gauge=StubRateGauge(),
            log=structlog.get_logger(),
            runner=runner,
            clock=clock,
            sleep=_sleep,
            tick_sec=tick_sec,
        ),
        clock,
    )


def _monitor_ctx(task_id: str = "t-hp") -> MonitorContext:
    now = datetime.now(tz=UTC)
    return MonitorContext(
        task=Task(id=task_id, title="T", description=None, status="in_progress"),
        task_dir=Path("/tmp"),
        attempt_dir=Path("/tmp"),
        coder=StubCoder(argv=[]),
        config=RuntimeConfig(),
        rate_gauge=StubRateGauge(),  # type: ignore[arg-type]
        task_log=structlog.get_logger(),
        ctx_log=structlog.get_logger(),
        context_limit=200_000,
        checkpoint_pct=75,
        kill_pct=90,
        attempt_budget_sec=None,
        started_at=now,
        last_event_at=now,
        last_stdout_at=now,
        last_probe_at=now,
        clock=FakeClock(start=now),
    )


def test_subprocess_runner_starts_real_process(tmp_path: Path) -> None:
    """SubprocessRunner.start spawns for real: pid, exit 0, recorded argv."""

    async def _run() -> None:
        proc = await SubprocessRunner().start(
            [sys.executable, "-c", "pass"], dict(os.environ), tmp_path
        )
        assert proc.pid > 0
        assert proc.returncode is None
        assert await proc.wait() == 0

    asyncio.run(_run())


def test_probe_health_kills_silent_worker_and_returns_its_outcome(tmp_path: Path) -> None:
    """A silent child is probed on fake time; a provider error kills it and
    the session returns that outcome instead of waiting forever."""
    coder = _ProbeCoder(TaskOutcomeRecord(outcome=TaskOutcome.FAILURE, reason="provider boom"))
    task = Task(id="t-probe", title="Test task", description="Do the thing.", status="in_progress")
    proc = FakeProcess(hang=True)
    ctx, _ = _fast_forward_ctx(tmp_path, task, coder, FakeProcessRunner([proc]))

    step_result = asyncio.run(asyncio.wait_for(LlmSession().run(ctx), timeout=10.0))
    result = step_result.outcome
    assert result is not None

    assert coder.probe_calls >= 1
    assert proc.terminated
    assert result.outcome == TaskOutcome.FAILURE
    assert result.reason == "provider boom"


def test_probe_rate_limit_is_ignored_until_rate_limit_silence_threshold(
    tmp_path: Path,
) -> None:
    """opencode retries provider rate limits itself: RATE_LIMIT probe reports
    inside the silence window never kill the session; a cancel still ends it
    as a shutdown, not a rate limit."""
    coder = _ProbeCoder(
        TaskOutcomeRecord(
            outcome=TaskOutcome.RATE_LIMIT,
            reason="opencode provider rate limit",
            resets_at=1234567890,
        )
    )
    task = Task(
        id="t-probe-patient", title="Test task", description="Do the thing.", status="in_progress"
    )
    proc = FakeProcess(hang=True)
    # One fake second per tick: silence crosses PROBE_SILENCE_SEC fast, but
    # stays far below RATE_LIMIT_PROBE_SILENCE_SEC when we cancel below.
    ctx, clock = _fast_forward_ctx(tmp_path, task, coder, FakeProcessRunner([proc]), tick_sec=1.0)
    session = LlmSession()

    async def _run_it():
        run_task = asyncio.create_task(session.run(ctx))
        for _ in range(10_000):
            if coder.probe_calls >= 1:
                break
            await asyncio.sleep(0)
        assert coder.probe_calls >= 1
        # Still inside the retry window: the probe reported, nothing died.
        assert clock.monotonic() < 300
        assert proc.terminated is False
        await session.cancel("supervisor_shutdown")
        step_result = await run_task
        return step_result.outcome

    result = asyncio.run(asyncio.wait_for(_run_it(), timeout=10.0))
    assert result is not None
    assert result.outcome != TaskOutcome.RATE_LIMIT


def test_probe_provider_error_kills_silent_session() -> None:
    """A non-rate-limit provider error past PROBE_SILENCE_SEC ends the session."""
    now = datetime.now(tz=UTC)
    mctx = _monitor_ctx()
    mctx.last_stdout_at = now
    mctx.last_probe_at = now
    mctx.last_event_at = now

    class _ErrCoder(StubCoder):
        def probe_health(self, task, task_dir, since, session_id=None):
            return TaskOutcomeRecord(outcome=TaskOutcome.FAILURE, reason="provider boom")

    mctx.coder = _ErrCoder(argv=[])
    later = now + timedelta(seconds=PROBE_SILENCE_SEC + 1)

    verdict = asyncio.run(HealthProbe().on_tick(later, mctx))

    assert verdict is not None
    assert verdict.kill
    assert verdict.outcome == TaskOutcome.FAILURE


def test_probe_rate_limit_patient_inside_window() -> None:
    """A RATE_LIMIT report inside RATE_LIMIT_PROBE_SILENCE_SEC is ignored."""
    assert RATE_LIMIT_PROBE_SILENCE_SEC > PROBE_SILENCE_SEC
    now = datetime.now(tz=UTC)
    mctx = _monitor_ctx()
    mctx.last_stdout_at = now
    mctx.last_probe_at = now
    mctx.last_event_at = now

    class _LimitedCoder(StubCoder):
        def probe_health(self, task, task_dir, since, session_id=None):
            return TaskOutcomeRecord(outcome=TaskOutcome.RATE_LIMIT, reason="limited")

    mctx.coder = _LimitedCoder(argv=[])
    inside = now + timedelta(seconds=PROBE_SILENCE_SEC + 1)

    verdict = asyncio.run(HealthProbe().on_tick(inside, mctx))

    assert verdict is None


def test_prompt_md_records_argv_last_element(tmp_path: Path) -> None:
    session, ctx, _, runner = _make_session(
        tmp_path,
        argv=[sys.executable, "-c", "pass", "PROMPT-TEXT-HERE"],
        procs=[FakeProcess()],
    )

    _run(session, ctx)

    prompt_path = tmp_path / "tasks" / "t-001" / "prompt.md"
    assert prompt_path.exists()
    assert prompt_path.read_text(encoding="utf-8") == "PROMPT-TEXT-HERE"
    assert runner.last_env["FLEET_LAUNCH_MODE"] == "fresh"
    assert runner.last_env["FLEET_ATTEMPT_N"] == "0"


def test_log_argv_redacts_prompt_text(tmp_path: Path) -> None:
    session, ctx, _, _ = _make_session(
        tmp_path,
        argv=[sys.executable, "-c", "pass", "SUPERSECRET-PROMPT"],
        procs=[FakeProcess()],
    )

    _run(session, ctx)

    log_path = tmp_path / "tasks" / "t-001" / "log.jsonl"
    lines = [json.loads(line) for line in log_path.read_text().splitlines() if line.strip()]
    started = [row for row in lines if row.get("event") == "subprocess_started"]
    assert len(started) == 1
    assert started[0]["argv"][-1] == "<see prompt.md>"
    assert "SUPERSECRET-PROMPT" not in log_path.read_text()
