"""Tests for LlmSession driven by a scripted FakeProcessRunner (no subprocesses)."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import structlog

from fleet.coders.claude import ClaudeCoder
from fleet.core.clock import FakeClock
from fleet.core.config import RuntimeConfig
from fleet.core.limits import PROBE_SILENCE_SEC, RATE_LIMIT_PROBE_SILENCE_SEC
from fleet.core.task import Event, Task, TaskOutcome, TaskOutcomeRecord
from fleet.state.paths import task_dir
from fleet.workers.base import StepContext, StepStatus
from fleet.workers.llm_session import LlmSession
from fleet.workers.session.monitors import HealthProbe, MonitorContext
from fleet.workers.session.process import SubprocessRunner
from tests.workers.fake_runner import FakeProcess, FakeProcessRunner

FIXTURES = Path(__file__).parent.parent / "fixtures"


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class StubCoder:
    name = "stub"
    context_limit: int = 200_000

    def __init__(self, argv: list[str], context_limit: int = 200_000) -> None:
        self._argv = argv
        self.context_limit = context_limit
        self._cli = ClaudeCoder(fleet_home=Path.cwd())
        self.runtime_config_calls: list[tuple[Path, Task]] = []

    def build_argv(self, task: Task, task_dir: Path, plan=None) -> list[str]:
        return self._argv

    def env(self, task: Task, task_dir: Path) -> dict[str, str]:
        return {
            "FLEET_TASK_ID": task.id,
            "FLEET_TASK_DIR": str(task_dir),
        }

    def normalize_event(self, raw_line: str) -> Event | None:
        return self._cli.normalize_event(raw_line)

    def write_runtime_config(self, project: Path, task: Task) -> None:
        self.runtime_config_calls.append((project, task))


class StubRateGauge:
    def __init__(self) -> None:
        self.updates: list[Event] = []

    def update(self, event: Event) -> None:
        self.updates.append(event)


def _make_ctx(
    tmp_path: Path,
    task: Task,
    coder,
    runner: FakeProcessRunner,
    *,
    config: RuntimeConfig | None = None,
    gauge: StubRateGauge | None = None,
) -> StepContext:
    return StepContext(
        task=task,
        task_dir=task_dir(tmp_path, task.id),
        workdir=tmp_path,
        fleet_home=tmp_path,
        coder=coder,
        config=config or RuntimeConfig(),
        rate_gauge=gauge or StubRateGauge(),
        log=structlog.get_logger(),
        runner=runner,
    )


def _make_session(
    tmp_path: Path,
    argv: list[str],
    procs: list[FakeProcess],
    *,
    task_id: str = "t-001",
    task_status: str = "in_progress",
    config: RuntimeConfig | None = None,
    context_limit: int = 200_000,
) -> tuple[LlmSession, StepContext, StubRateGauge, FakeProcessRunner]:
    task = Task(id=task_id, title="Test task", description="Do the thing.", status=task_status)
    gauge = StubRateGauge()
    runner = FakeProcessRunner(procs)
    ctx = _make_ctx(
        tmp_path,
        task,
        StubCoder(argv=argv, context_limit=context_limit),
        runner,
        config=config,
        gauge=gauge,
    )
    return LlmSession(), ctx, gauge, runner


def _fixture_lines(name: str) -> list[str]:
    return [line for line in (FIXTURES / name).read_text().splitlines() if line.strip()]


def _run(session: LlmSession, ctx: StepContext) -> TaskOutcomeRecord:
    step_result = asyncio.run(session.run(ctx))
    assert step_result.status == StepStatus.OUTCOME
    assert step_result.outcome is not None
    return step_result.outcome


# ---------------------------------------------------------------------------
# Test: Clean-exit SUCCESS
# ---------------------------------------------------------------------------


def test_clean_exit_returns_success(tmp_path: Path) -> None:
    session, ctx, _, _ = _make_session(
        tmp_path,
        argv=[sys.executable, "-c", "pass"],
        procs=[FakeProcess(lines=_fixture_lines("stream_clean_exit.jsonl"))],
    )

    result = _run(session, ctx)

    assert result.outcome == TaskOutcome.SUCCESS
    assert result.exit_code == 0


def test_clean_exit_writes_events_jsonl(tmp_path: Path) -> None:
    session, ctx, _, _ = _make_session(
        tmp_path,
        argv=[sys.executable, "-c", "pass"],
        procs=[FakeProcess(lines=_fixture_lines("stream_clean_exit.jsonl"))],
    )

    _run(session, ctx)

    events_path = tmp_path / "tasks" / "t-001" / "events.jsonl"
    assert events_path.exists()
    records = [json.loads(line) for line in events_path.read_text().splitlines() if line.strip()]
    assert len(records) >= 1


def test_clean_exit_creates_task_dir_and_log(tmp_path: Path) -> None:
    session, ctx, _, _ = _make_session(
        tmp_path, argv=[sys.executable, "-c", "pass"], procs=[FakeProcess()]
    )

    _run(session, ctx)

    assert (tmp_path / "tasks" / "t-001").is_dir()
    assert (tmp_path / "tasks" / "t-001" / "log.jsonl").exists()


# ---------------------------------------------------------------------------
# Test: Rate-limit rejection → RATE_LIMIT
# ---------------------------------------------------------------------------


def _rate_limit_proc() -> FakeProcess:
    rate_event = json.dumps(
        {"api_error_status": 429, "error": "rate_limit", "resetsAt": 9999999999}
    )
    return FakeProcess(lines=[rate_event], hang=True)


def test_rate_limit_rejection_returns_rate_limit(tmp_path: Path) -> None:
    session, ctx, _, _ = _make_session(
        tmp_path, argv=[sys.executable, "-c", "pass"], procs=[_rate_limit_proc()]
    )

    result = _run(session, ctx)

    assert result.outcome == TaskOutcome.RATE_LIMIT
    assert result.resets_at == 9999999999


def test_rate_limit_reason_mentions_resets_at(tmp_path: Path) -> None:
    """LlmSession makes no queue calls; it returns a RATE_LIMIT record with a
    resets_at-bearing reason for the caller (orchestrator/reap.py) to act on."""
    session, ctx, _, _ = _make_session(
        tmp_path, argv=[sys.executable, "-c", "pass"], procs=[_rate_limit_proc()]
    )

    result = _run(session, ctx)

    assert result.outcome == TaskOutcome.RATE_LIMIT
    assert "rate_limit" in result.reason
    assert "9999999999" in result.reason


def test_rate_limit_no_resets_at_gives_none(tmp_path: Path) -> None:
    rate_event = json.dumps({"api_error_status": 429, "error": "rate_limit"})
    session, ctx, _, _ = _make_session(
        tmp_path,
        argv=[sys.executable, "-c", "pass"],
        procs=[FakeProcess(lines=[rate_event], hang=True)],
    )

    result = _run(session, ctx)

    assert result.outcome == TaskOutcome.RATE_LIMIT
    assert result.resets_at is None


# ---------------------------------------------------------------------------
# Test: legacy .context_pressure marker file is ignored (removed in spec 5)
# ---------------------------------------------------------------------------


def test_legacy_context_pressure_marker_is_ignored(tmp_path: Path) -> None:
    """The old marker file no longer drives outcomes; CONTEXT_PRESSURE now
    comes from usage counters and CLI overflow errors only."""
    session, ctx, _, _ = _make_session(
        tmp_path, argv=[sys.executable, "-c", "pass"], procs=[FakeProcess()]
    )
    marker = tmp_path / "tasks" / "t-001" / ".context_pressure"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.touch()

    result = _run(session, ctx)

    assert result.outcome == TaskOutcome.SUCCESS
    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# Test: Non-zero rc → FAILURE + stderr_tail
# ---------------------------------------------------------------------------


def test_nonzero_rc_returns_failure(tmp_path: Path) -> None:
    session, ctx, _, _ = _make_session(
        tmp_path,
        argv=[sys.executable, "-c", "pass"],
        procs=[FakeProcess(exit_code=1, stderr_text="something went wrong\n")],
    )

    result = _run(session, ctx)

    assert result.outcome == TaskOutcome.FAILURE
    assert result.exit_code == 1


def test_nonzero_rc_populates_stderr_tail(tmp_path: Path) -> None:
    session, ctx, _, _ = _make_session(
        tmp_path,
        argv=[sys.executable, "-c", "pass"],
        procs=[FakeProcess(exit_code=1, stderr_text="something went wrong\n")],
    )

    result = _run(session, ctx)

    assert result.stderr_tail is not None
    assert "something went wrong" in result.stderr_tail


# ---------------------------------------------------------------------------
# Test: cancel() → killed/cancelled outcomes on a hanging child
# ---------------------------------------------------------------------------


def test_cancel_sigkill_escalation(tmp_path: Path) -> None:
    proc = FakeProcess(hang=True)
    session, ctx, _, _ = _make_session(tmp_path, argv=[sys.executable, "-c", "pass"], procs=[proc])

    async def _run_it() -> None:
        run_task = asyncio.create_task(session.run(ctx))
        await asyncio.sleep(0.2)
        await session.cancel("supervisor_shutdown")
        step_result = await run_task
        result = step_result.outcome
        assert result is not None
        assert result.outcome == TaskOutcome.FAILURE
        assert result.reason == "supervisor_shutdown"

    asyncio.run(_run_it())
    assert proc.terminated


def test_kill_returns_killed_with_reason(tmp_path: Path) -> None:
    proc = FakeProcess(hang=True)
    session, ctx, _, _ = _make_session(tmp_path, argv=[sys.executable, "-c", "pass"], procs=[proc])

    async def _run_it() -> None:
        run_task = asyncio.create_task(session.run(ctx))
        await asyncio.sleep(0.2)
        await session.cancel("stalled")
        step_result = await run_task
        result = step_result.outcome
        assert result is not None
        assert result.outcome == TaskOutcome.KILLED
        assert result.reason == "stalled"

    asyncio.run(_run_it())
    assert proc.terminated


# ---------------------------------------------------------------------------
# Test: BEADS_DIR injection (asserted on the recorded start env)
# ---------------------------------------------------------------------------


def test_beads_dir_injected_into_subprocess(tmp_path: Path, monkeypatch) -> None:
    """Agent subprocess receives BEADS_DIR ending with '.beads'."""
    # Insulate from a real BEADS_DIR the test host session may already export
    # (e.g. when pytest itself runs inside a fleet-managed worktree).
    monkeypatch.delenv("BEADS_DIR", raising=False)
    session, ctx, _, runner = _make_session(
        tmp_path, argv=[sys.executable, "-c", "pass"], procs=[FakeProcess()]
    )

    result = _run(session, ctx)

    assert result.outcome == TaskOutcome.SUCCESS
    assert runner.last_env["BEADS_DIR"] == str(tmp_path / ".beads")


class _BeadsDirCoder(StubCoder):
    """StubCoder that returns an explicit BEADS_DIR in env."""

    def env(self, task: Task, task_dir: Path) -> dict[str, str]:
        env = super().env(task, task_dir)
        env["BEADS_DIR"] = "/custom/.beads"
        return env


def test_subprocess_sees_coder_provided_beads_dir(tmp_path: Path) -> None:
    """When coder provides BEADS_DIR, LlmSession must not override it."""
    task = Task(id="t-002", title="Test task", description=None, status="in_progress")
    runner = FakeProcessRunner([FakeProcess()])
    ctx = _make_ctx(tmp_path, task, _BeadsDirCoder(argv=[sys.executable, "-c", "pass"]), runner)

    result = _run(LlmSession(), ctx)

    assert result.outcome == TaskOutcome.SUCCESS
    assert runner.last_env["BEADS_DIR"] == "/custom/.beads"


# -----------------------------------------------------------------------
# Test: tool_use log records tool name from normalized field
# -----------------------------------------------------------------------


class _ToolUseCoder(StubCoder):
    def __init__(self, tool_name: str) -> None:
        super().__init__(argv=[sys.executable, "-c", "pass"])
        self._tool_name = tool_name

    def normalize_event(self, raw_line: str) -> Event | None:
        if "emit_tool_use" in raw_line:
            return Event(
                kind="tool_use",
                raw={"name": self._tool_name},
                ts=datetime.now(),
                tool_name=self._tool_name,
            )
        return self._cli.normalize_event(raw_line)


tool_use_event_json = json.dumps({"_": True, "emit_tool_use": True})


def test_runner_logs_tool_use_name(tmp_path: Path) -> None:
    """Coder emitting a tool_use event -> events.jsonl contains it with correct tool_name."""
    coder = _ToolUseCoder("bash")
    task = Task(id="t-tu", title="Test task", description=None, status="in_progress")
    runner = FakeProcessRunner([FakeProcess(lines=[tool_use_event_json])])
    ctx = _make_ctx(tmp_path, task, coder, runner)

    result = _run(LlmSession(), ctx)

    assert result.outcome == TaskOutcome.SUCCESS
    events_path = tmp_path / "tasks" / "t-tu" / "events.jsonl"
    records = [json.loads(line) for line in events_path.read_text().splitlines() if line.strip()]
    tool_use_records = [r for r in records if r.get("kind") == "tool_use"]
    assert len(tool_use_records) >= 1
    assert tool_use_records[-1].get("tool_name") == "bash"


# -----------------------------------------------------------------------
# Test: session_started dedup – multiple events, only one log line
# -----------------------------------------------------------------------


class _SessionStartedCoder(StubCoder):
    def __init__(self) -> None:
        super().__init__(argv=[sys.executable, "-c", "pass"])
        self._count = 0

    def normalize_event(self, raw_line: str) -> Event | None:
        if "emit_session" in raw_line:
            self._count += 1
            sid = f"s-{self._count}"
            return Event(
                kind="session_started",
                raw={"session_id": sid},
                ts=datetime.now(),
                session_id=sid,
            )
        return None


ss_event_1 = json.dumps({"_": True, "emit_session": True, "session_id": "s-1"})
ss_event_2 = json.dumps({"_": True, "emit_session": True, "session_id": "s-2"})


def test_session_started_dedup(tmp_path: Path) -> None:
    """Two session_started events -> both in events.jsonl, run completes SUCCESS."""
    coder = _SessionStartedCoder()
    task = Task(id="t-ss", title="Test task", description=None, status="in_progress")
    runner = FakeProcessRunner([FakeProcess(lines=[ss_event_1, ss_event_2])])
    ctx = _make_ctx(tmp_path, task, coder, runner)

    _run(LlmSession(), ctx)

    events_path = tmp_path / "tasks" / "t-ss" / "events.jsonl"
    records = [json.loads(line) for line in events_path.read_text().splitlines() if line.strip()]
    session_started_records = [r for r in records if r.get("kind") == "session_started"]
    assert len(session_started_records) == 2


# ---------------------------------------------------------------------------
# Test: Context usage bucket logging at 10% steps
# ---------------------------------------------------------------------------


def _usage_line(input_tokens: int) -> str:
    return json.dumps(
        {
            "type": "assistant",
            "message": {"content": [], "usage": {"input_tokens": input_tokens}},
            "session_id": "s-ctx",
        }
    )


def test_context_usage_bucket_logging(tmp_path: Path) -> None:
    """Usage events crossing 10% and 20% of context_limit produce two context_usage log lines."""
    session, ctx, _, _ = _make_session(
        tmp_path,
        argv=[sys.executable, "-c", "pass"],
        procs=[FakeProcess(lines=[_usage_line(101), _usage_line(201)])],
        context_limit=1_000,
    )

    result = _run(session, ctx)

    assert result.outcome == TaskOutcome.SUCCESS
    log_path = tmp_path / "tasks" / "t-001" / "log.jsonl"
    log_records = [json.loads(line) for line in log_path.read_text().splitlines() if line.strip()]
    context_usage_events = [r for r in log_records if r.get("event") == "context_usage"]
    # The first usage at 101 (bucket 1) logs, as does the second at 201 (bucket 2).
    assert len(context_usage_events) >= 2


def test_context_usage_bucket_logging_skips_same_bucket(tmp_path: Path) -> None:
    """Usage events within same 10% bucket produce only one context_usage log line."""
    session, ctx, _, _ = _make_session(
        tmp_path,
        argv=[sys.executable, "-c", "pass"],
        procs=[FakeProcess(lines=[_usage_line(150), _usage_line(120)])],
        context_limit=1_000,
    )

    result = _run(session, ctx)

    assert result.outcome == TaskOutcome.SUCCESS
    log_path = tmp_path / "tasks" / "t-001" / "log.jsonl"
    log_records = [json.loads(line) for line in log_path.read_text().splitlines() if line.strip()]
    context_usage_events = [r for r in log_records if r.get("event") == "context_usage"]
    # Both are in 10-19% range (bucket=1), so only one log line.
    assert len(context_usage_events) == 1


# ---------------------------------------------------------------------------
# Test: the runner seam spawns real processes (only SubprocessRunner touches asyncio)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Test: probe_health kills a silent session, patient rate limits survive
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Test: HealthProbe thresholds as pure unit tests (real limits constants)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# prompt.md is recorded; log.jsonl argv line stays small
# ---------------------------------------------------------------------------


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
