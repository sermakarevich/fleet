import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

import structlog

import fleet.workers.session.monitors as monitors_mod
from fleet.coders.claude import ClaudeCoder
from fleet.core.config import RuntimeConfig
from fleet.core.task import Event, Task, TaskOutcome, TaskOutcomeRecord
from fleet.state.paths import task_dir as _task_dir_path
from fleet.workers.base import StepContext
from fleet.workers.llm_session import LlmSession

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
        self._cli = ClaudeCoder()
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

    def update(self, evt: Event) -> None:
        self.updates.append(evt)


def _make_ctx(
    tmp_path: Path,
    task: Task,
    coder,
    *,
    config: RuntimeConfig | None = None,
    gauge: StubRateGauge | None = None,
) -> StepContext:
    return StepContext(
        task=task,
        task_dir=_task_dir_path(tmp_path, task.id),
        project_root=tmp_path,
        fleet_home=tmp_path,
        coder=coder,
        config=config or RuntimeConfig(),
        rate_gauge=gauge or StubRateGauge(),
        log=structlog.get_logger(),
    )


def _make_session(
    tmp_path: Path,
    argv: list[str],
    *,
    task_id: str = "t-001",
    task_status: str = "in_progress",
    config: RuntimeConfig | None = None,
    context_limit: int = 200_000,
) -> tuple[LlmSession, StepContext, StubRateGauge]:
    task = Task(id=task_id, title="Test task", description="Do the thing.", status=task_status)
    gauge = StubRateGauge()
    ctx = _make_ctx(
        tmp_path,
        task,
        StubCoder(argv=argv, context_limit=context_limit),
        config=config,
        gauge=gauge,
    )
    return LlmSession(), ctx, gauge


def _run(session: LlmSession, ctx: StepContext) -> TaskOutcomeRecord:
    step_result = asyncio.run(session.run(ctx))
    assert step_result.status == "outcome"
    assert step_result.outcome is not None
    return step_result.outcome


# ---------------------------------------------------------------------------
# Test: Clean-exit SUCCESS
# ---------------------------------------------------------------------------


def test_clean_exit_returns_success(tmp_path: Path) -> None:
    lines = [
        line
        for line in (FIXTURES / "stream_clean_exit.jsonl").read_text().splitlines()
        if line.strip()
    ]
    script = (
        "import sys\n"
        f"lines = {lines!r}\n"
        "for line in lines:\n"
        "    sys.stdout.write(line + '\\n')\n"
        "    sys.stdout.flush()\n"
    )
    session, ctx, _ = _make_session(tmp_path, argv=[sys.executable, "-c", script])

    result = _run(session, ctx)

    assert result.outcome == TaskOutcome.SUCCESS
    assert result.exit_code == 0


def test_clean_exit_writes_events_jsonl(tmp_path: Path) -> None:
    lines = [
        line
        for line in (FIXTURES / "stream_clean_exit.jsonl").read_text().splitlines()
        if line.strip()
    ]
    script = (
        "import sys\n"
        f"lines = {lines!r}\n"
        "for line in lines:\n"
        "    sys.stdout.write(line + '\\n')\n"
        "    sys.stdout.flush()\n"
    )
    session, ctx, _ = _make_session(tmp_path, argv=[sys.executable, "-c", script])

    _run(session, ctx)

    events_path = tmp_path / "tasks" / "t-001" / "events.jsonl"
    assert events_path.exists()
    records = [json.loads(line) for line in events_path.read_text().splitlines() if line.strip()]
    assert len(records) >= 1


def test_clean_exit_creates_task_dir_and_log(tmp_path: Path) -> None:
    session, ctx, _ = _make_session(
        tmp_path, argv=[sys.executable, "-c", "import sys; sys.exit(0)"]
    )

    _run(session, ctx)

    assert (tmp_path / "tasks" / "t-001").is_dir()
    assert (tmp_path / "tasks" / "t-001" / "log.jsonl").exists()


# ---------------------------------------------------------------------------
# Test: Rate-limit rejection → RATE_LIMIT + queue.release
# ---------------------------------------------------------------------------


def test_rate_limit_rejection_returns_rate_limit(tmp_path: Path) -> None:
    rate_event = json.dumps(
        {"api_error_status": 429, "error": "rate_limit", "resetsAt": 9999999999}
    )
    script = (
        "import sys, time\n"
        f"sys.stdout.write({rate_event!r} + '\\n')\n"
        "sys.stdout.flush()\n"
        "time.sleep(60)\n"
    )
    session, ctx, _ = _make_session(
        tmp_path,
        argv=[sys.executable, "-c", script],
    )

    result = _run(session, ctx)

    assert result.outcome == TaskOutcome.RATE_LIMIT
    assert result.resets_at == 9999999999


def test_rate_limit_reason_mentions_resets_at(tmp_path: Path) -> None:
    """LlmSession makes no queue calls; it returns a RATE_LIMIT record with a
    resets_at-bearing reason for the caller (orchestrator/reap.py) to act on."""
    rate_event = json.dumps(
        {"api_error_status": 429, "error": "rate_limit", "resetsAt": 9999999999}
    )
    script = (
        "import sys, time\n"
        f"sys.stdout.write({rate_event!r} + '\\n')\n"
        "sys.stdout.flush()\n"
        "time.sleep(60)\n"
    )
    session, ctx, _ = _make_session(
        tmp_path,
        argv=[sys.executable, "-c", script],
    )

    result = _run(session, ctx)

    assert result.outcome == TaskOutcome.RATE_LIMIT
    assert "rate_limit" in result.reason
    assert "9999999999" in result.reason


def test_rate_limit_no_resets_at_gives_none(tmp_path: Path) -> None:
    rate_event = json.dumps({"api_error_status": 429, "error": "rate_limit"})
    script = (
        "import sys, time\n"
        f"sys.stdout.write({rate_event!r} + '\\n')\n"
        "sys.stdout.flush()\n"
        "time.sleep(60)\n"
    )
    session, ctx, _ = _make_session(tmp_path, argv=[sys.executable, "-c", script])

    result = _run(session, ctx)

    assert result.outcome == TaskOutcome.RATE_LIMIT
    assert result.resets_at is None


# ---------------------------------------------------------------------------
# Test: legacy .context_pressure marker file is ignored (removed in spec 5)
# ---------------------------------------------------------------------------

_LEGACY_CP_SCRIPT = (
    "import sys, os\n"
    "from pathlib import Path\n"
    "p = Path(os.environ['FLEET_TASK_DIR'])\n"
    "p.mkdir(parents=True, exist_ok=True)\n"
    "(p / '.context_pressure').touch()\n"
    "sys.exit(0)\n"
)


def test_legacy_context_pressure_marker_is_ignored(tmp_path: Path) -> None:
    """The old marker file no longer drives outcomes; CONTEXT_PRESSURE now
    comes from usage counters and CLI overflow errors only."""
    session, ctx, _ = _make_session(tmp_path, argv=[sys.executable, "-c", _LEGACY_CP_SCRIPT])

    result = _run(session, ctx)

    assert result.outcome == TaskOutcome.SUCCESS
    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# Test: Non-zero rc → FAILURE + stderr_tail
# ---------------------------------------------------------------------------


def test_nonzero_rc_returns_failure(tmp_path: Path) -> None:
    script = (
        "import sys\nsys.stderr.write('something went wrong\\n')\nsys.stderr.flush()\nsys.exit(1)\n"
    )
    session, ctx, _ = _make_session(tmp_path, argv=[sys.executable, "-c", script])

    result = _run(session, ctx)

    assert result.outcome == TaskOutcome.FAILURE
    assert result.exit_code == 1


def test_nonzero_rc_populates_stderr_tail(tmp_path: Path) -> None:
    script = (
        "import sys\nsys.stderr.write('something went wrong\\n')\nsys.stderr.flush()\nsys.exit(1)\n"
    )
    session, ctx, _ = _make_session(tmp_path, argv=[sys.executable, "-c", script])

    result = _run(session, ctx)

    assert result.stderr_tail is not None
    assert "something went wrong" in result.stderr_tail


# ---------------------------------------------------------------------------
# Test: cancel() → SIGKILL escalation when child ignores SIGTERM
# ---------------------------------------------------------------------------


def test_cancel_sigkill_escalation(tmp_path: Path) -> None:
    script = "import signal, time\nsignal.signal(signal.SIGTERM, signal.SIG_IGN)\ntime.sleep(60)\n"
    session, ctx, _ = _make_session(
        tmp_path,
        argv=[sys.executable, "-c", script],
    )

    async def _run_it() -> None:
        run_task = asyncio.create_task(session.run(ctx))
        await asyncio.sleep(0.3)
        await session.cancel("supervisor_shutdown")
        step_result = await run_task
        result = step_result.outcome
        assert result is not None
        assert result.outcome == TaskOutcome.FAILURE
        assert result.reason == "supervisor_shutdown"

    asyncio.run(_run_it())


def test_kill_returns_killed_with_reason(tmp_path: Path) -> None:
    script = "import signal, time\nsignal.signal(signal.SIGTERM, signal.SIG_IGN)\ntime.sleep(60)\n"
    session, ctx, _ = _make_session(
        tmp_path,
        argv=[sys.executable, "-c", script],
    )

    async def _run_it() -> None:
        run_task = asyncio.create_task(session.run(ctx))
        await asyncio.sleep(0.3)
        await session.cancel("stalled")
        step_result = await run_task
        result = step_result.outcome
        assert result is not None
        assert result.outcome == TaskOutcome.KILLED
        assert result.reason == "stalled"

    asyncio.run(_run_it())


# ---------------------------------------------------------------------------
# Test: BEADS_DIR injection
# ---------------------------------------------------------------------------


def test_beads_dir_injected_into_subprocess(tmp_path: Path, monkeypatch) -> None:
    """Agent subprocess receives BEADS_DIR ending with '.beads'."""
    # Insulate from a real BEADS_DIR the test host session may already export
    # (e.g. when pytest itself runs inside a fleet-managed worktree).
    monkeypatch.delenv("BEADS_DIR", raising=False)
    beads_dir = str(tmp_path / ".beads")
    script = (
        f"import os, sys\nsys.exit(0 if os.environ.get('BEADS_DIR','') == {beads_dir!r} else 3)\n"
    )
    session, ctx, _ = _make_session(tmp_path, argv=[sys.executable, "-c", script])

    result = _run(session, ctx)

    assert result.outcome == TaskOutcome.SUCCESS
    assert result.exit_code == 0


class _BeadsDirCoder(StubCoder):
    """StubCoder that returns an explicit BEADS_DIR in env."""

    def env(self, task: Task, task_dir: Path) -> dict[str, str]:
        env = super().env(task, task_dir)
        env["BEADS_DIR"] = "/custom/.beads"
        return env


def test_subprocess_sees_coder_provided_beads_dir(tmp_path: Path) -> None:
    """When coder provides BEADS_DIR, LlmSession must not override it."""
    script = (
        "import os, sys\nsys.exit(0 if os.environ.get('BEADS_DIR') == '/custom/.beads' else 3)\n"
    )
    task = Task(id="t-002", title="Test task", description=None, status="in_progress")
    coder = _BeadsDirCoder(argv=[sys.executable, "-c", script])
    ctx = _make_ctx(tmp_path, task, coder)

    result = _run(LlmSession(), ctx)

    assert result.outcome == TaskOutcome.SUCCESS
    assert result.exit_code == 0


# -----------------------------------------------------------------------
# Test: tool_use log records tool name from normalized field
# -----------------------------------------------------------------------


class _ToolUseCoder(StubCoder):
    def __init__(self, tool_name: str) -> None:
        super().__init__(argv=[sys.executable, "-c", tool_use_script])
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
tool_use_script = (
    "import sys\n"
    f"sys.stdout.write({tool_use_event_json!r} + '\\n')\n"
    "sys.stdout.flush()\n"
    "sys.exit(0)\n"
)


def test_runner_logs_tool_use_name(tmp_path: Path) -> None:
    """Coder emitting a tool_use event -> events.jsonl contains it with correct tool_name."""
    coder = _ToolUseCoder("bash")
    task = Task(id="t-tu", title="Test task", description=None, status="in_progress")
    ctx = _make_ctx(tmp_path, task, coder)

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
        super().__init__(argv=[sys.executable, "-c", ss_script])
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
ss_script = (
    "import sys\n"
    f"sys.stdout.write({ss_event_1!r} + '\\n' + {ss_event_2!r} + '\\n')\n"
    "sys.stdout.flush()\n"
    "sys.exit(0)\n"
)


def test_session_started_dedup(tmp_path: Path) -> None:
    """Two session_started events -> both in events.jsonl, run completes SUCCESS."""
    coder = _SessionStartedCoder()
    task = Task(id="t-ss", title="Test task", description=None, status="in_progress")
    ctx = _make_ctx(tmp_path, task, coder)

    _run(LlmSession(), ctx)

    events_path = tmp_path / "tasks" / "t-ss" / "events.jsonl"
    records = [json.loads(line) for line in events_path.read_text().splitlines() if line.strip()]
    session_started_records = [r for r in records if r.get("kind") == "session_started"]
    assert len(session_started_records) == 2


# ---------------------------------------------------------------------------
# Test: Context usage bucket logging at 10% steps
# ---------------------------------------------------------------------------


def test_context_usage_bucket_logging(tmp_path: Path) -> None:
    """Usage events crossing 10% and 20% of context_limit produce two context_usage log lines."""
    event_10 = json.dumps(
        {
            "type": "assistant",
            "message": {"content": [], "usage": {"input_tokens": 101}},
            "session_id": "s-ctx",
        }
    )
    event_20 = json.dumps(
        {
            "type": "assistant",
            "message": {"content": [], "usage": {"input_tokens": 201}},
            "session_id": "s-ctx",
        }
    )
    clean_script = (
        "import sys, json\n"
        f"sys.stdout.write({event_10!r} + '\\n')\n"
        "sys.stdout.flush()\n"
        f"sys.stdout.write({event_20!r} + '\\n')\n"
        "sys.stdout.flush()\n"
        "sys.exit(0)\n"
    )
    session, ctx, _ = _make_session(
        tmp_path,
        argv=[sys.executable, "-c", clean_script],
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
    event_15 = json.dumps(
        {
            "type": "assistant",
            "message": {"content": [], "usage": {"input_tokens": 150}},
            "session_id": "s-ctx",
        }
    )
    event_12 = json.dumps(
        {
            "type": "assistant",
            "message": {"content": [], "usage": {"input_tokens": 120}},
            "session_id": "s-ctx",
        }
    )
    clean_script = (
        "import sys, json\n"
        f"sys.stdout.write({event_15!r} + '\\n')\n"
        "sys.stdout.flush()\n"
        f"sys.stdout.write({event_12!r} + '\\n')\n"
        "sys.stdout.flush()\n"
        "sys.exit(0)\n"
    )
    session, ctx, _ = _make_session(
        tmp_path,
        argv=[sys.executable, "-c", clean_script],
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
# Test: spawn uses start_new_session (own process group)
# ---------------------------------------------------------------------------


def test_spawn_uses_new_session(tmp_path: Path, monkeypatch) -> None:
    """LlmSession.run must spawn the coder with start_new_session=True."""
    captured: dict = {}

    class _FakeStdout:
        _limit = 0

        async def readline(self) -> bytes:
            return b""

    class _FakeProc:
        pid = 123456
        returncode: int | None = None
        stdout = _FakeStdout()

        def send_signal(self, sig) -> None:
            pass

        async def wait(self) -> int:
            self.returncode = 0
            return 0

    async def _fake_create(*args, **kwargs):
        captured.update(kwargs)
        captured["args"] = args
        return _FakeProc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_create)

    session, ctx, _ = _make_session(
        tmp_path, argv=[sys.executable, "-c", "import sys; sys.exit(0)"]
    )

    result = _run(session, ctx)

    assert captured["start_new_session"] is True
    assert result.outcome == TaskOutcome.SUCCESS


# ---------------------------------------------------------------------------
# Test: probe_health detects a hung provider and kills the silent worker
# ---------------------------------------------------------------------------


def test_probe_health_kills_silent_worker_and_returns_its_outcome(
    tmp_path: Path, monkeypatch
) -> None:
    """A silent subprocess (no stdout) is probed periodically; once probe_health
    reports a provider error, the runner kills the process group and returns
    that outcome instead of waiting for the process to exit on its own."""

    monkeypatch.setattr(monitors_mod, "MONITOR_TICK_SEC", 0.01)
    monkeypatch.setattr(monitors_mod, "PROBE_SILENCE_SEC", -1)
    monkeypatch.setattr(monitors_mod, "RATE_LIMIT_PROBE_SILENCE_SEC", -1)

    class _FakeStdout:
        _limit = 0

        def __init__(self, proc: "_FakeProc") -> None:
            self._proc = proc

        async def readline(self) -> bytes:
            while self._proc.returncode is None:
                await asyncio.sleep(0.01)
            return b""

    class _FakeProc:
        pid = 987654
        returncode: int | None = None

        def __init__(self) -> None:
            self.stdout = _FakeStdout(self)

        def send_signal(self, sig) -> None:
            self.returncode = -sig

        async def wait(self) -> int:
            while self.returncode is None:
                await asyncio.sleep(0.01)
            return self.returncode

    async def _fake_create(*args, **kwargs):
        return _FakeProc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_create)

    class FakeProbeCoder(StubCoder):
        def __init__(self, argv: list[str]) -> None:
            super().__init__(argv=argv)
            self.probe_calls = 0

        def probe_health(self, task, task_dir, started_at):
            self.probe_calls += 1
            if self.probe_calls < 2:
                return None
            return TaskOutcomeRecord(
                outcome=TaskOutcome.RATE_LIMIT,
                reason="opencode provider rate limit",
                resets_at=1234567890,
            )

    task = Task(id="t-probe", title="Test task", description="Do the thing.", status="in_progress")
    coder = FakeProbeCoder(argv=[sys.executable, "-c", "pass"])
    ctx = _make_ctx(tmp_path, task, coder)

    step_result = asyncio.run(asyncio.wait_for(LlmSession().run(ctx), timeout=10.0))
    result = step_result.outcome
    assert result is not None

    assert coder.probe_calls >= 2
    assert result.outcome == TaskOutcome.RATE_LIMIT
    assert result.reason == "opencode provider rate limit"


# ---------------------------------------------------------------------------
# Test: a rate limit the CLI is still retrying does not kill the session
# ---------------------------------------------------------------------------


def test_probe_rate_limit_is_ignored_until_rate_limit_silence_threshold(
    tmp_path: Path, monkeypatch
) -> None:
    """opencode retries provider rate limits itself. When probe_health reports
    RATE_LIMIT but the session has been silent for less than
    RATE_LIMIT_PROBE_SILENCE_SEC, the step keeps waiting and the session is
    allowed to recover and finish on its own."""

    monkeypatch.setattr(monitors_mod, "MONITOR_TICK_SEC", 0.01)
    monkeypatch.setattr(monitors_mod, "PROBE_SILENCE_SEC", -1)
    monkeypatch.setattr(monitors_mod, "RATE_LIMIT_PROBE_SILENCE_SEC", 3600)

    class _FakeStdout:
        _limit = 0
        calls = 0

        async def readline(self) -> bytes:
            self.calls += 1
            if self.calls <= 3:
                await asyncio.sleep(0.05)  # longer than MONITOR_TICK_SEC -> probes fire
                return b"not-json\n"
            return b""

    class _FakeProc:
        pid = 987655
        returncode: int | None = None
        stdout = _FakeStdout()
        killed = False

        def send_signal(self, sig) -> None:
            self.killed = True
            self.returncode = -sig

        async def wait(self) -> int:
            if self.returncode is None:
                self.returncode = 0
            return self.returncode

    fake_proc = _FakeProc()

    async def _fake_create(*args, **kwargs):
        return fake_proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_create)

    class AlwaysRateLimited(StubCoder):
        def __init__(self, argv: list[str]) -> None:
            super().__init__(argv=argv)
            self.probe_calls = 0

        def probe_health(self, task, task_dir, since):
            self.probe_calls += 1
            return TaskOutcomeRecord(
                outcome=TaskOutcome.RATE_LIMIT,
                reason="opencode provider rate limit",
                resets_at=1234567890,
            )

    task = Task(
        id="t-probe-patient", title="Test task", description="Do the thing.", status="in_progress"
    )
    coder = AlwaysRateLimited(argv=[sys.executable, "-c", "pass"])
    ctx = _make_ctx(tmp_path, task, coder)

    step_result = asyncio.run(asyncio.wait_for(LlmSession().run(ctx), timeout=10.0))
    result = step_result.outcome
    assert result is not None

    assert coder.probe_calls >= 1
    assert fake_proc.killed is False
    assert result.outcome != TaskOutcome.RATE_LIMIT


# ---------------------------------------------------------------------------
# prompt.md is recorded; log.jsonl argv line stays small
# ---------------------------------------------------------------------------


def test_prompt_md_records_argv_last_element(tmp_path: Path) -> None:
    session, ctx, _ = _make_session(
        tmp_path,
        argv=[sys.executable, "-c", "import sys; sys.exit(0)", "PROMPT-TEXT-HERE"],
    )

    _run(session, ctx)

    prompt_path = tmp_path / "tasks" / "t-001" / "prompt.md"
    assert prompt_path.exists()
    assert prompt_path.read_text(encoding="utf-8") == "PROMPT-TEXT-HERE"


def test_log_argv_redacts_prompt_text(tmp_path: Path) -> None:
    session, ctx, _ = _make_session(
        tmp_path,
        argv=[sys.executable, "-c", "import sys; sys.exit(0)", "SUPERSECRET-PROMPT"],
    )

    _run(session, ctx)

    log_path = tmp_path / "tasks" / "t-001" / "log.jsonl"
    lines = [json.loads(line) for line in log_path.read_text().splitlines() if line.strip()]
    started = [row for row in lines if row.get("event") == "subprocess_started"]
    assert len(started) == 1
    assert started[0]["argv"][-1] == "<see prompt.md>"
    assert "SUPERSECRET-PROMPT" not in log_path.read_text()
