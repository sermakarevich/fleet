import asyncio
import json
from datetime import datetime
import sys
from pathlib import Path

import structlog

from fleet.coders.claude import ClaudeCoder
from fleet.runner import TaskRunner
from fleet.schemas import Event, RuntimeConfig, Task, TaskOutcome

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

    def build_argv(self, task: Task, task_dir: Path) -> list[str]:
        return self._argv

    def env(self, task: Task, task_dir: Path) -> dict[str, str]:
        return {
            "FLEET_TASK_ID": task.id,
            "FLEET_TASK_DIR": str(task_dir),
            "FLEET_ARTIFACT_DIR": str(task_dir / "artifacts"),
        }

    def normalize_event(self, raw_line: str) -> Event | None:
        return self._cli.normalize_event(raw_line)

    def write_runtime_config(self, project: Path, task: Task) -> None:
        self.runtime_config_calls.append((project, task))


class StubQueue:
    def __init__(self, task_status: str = "in_progress") -> None:
        self._task_status = task_status
        self.released: list[tuple[str, str]] = []

    def claim_next(self, claimer_id: str) -> Task | None:
        return None

    def release(self, task_id: str, reason: str = "") -> None:
        self.released.append((task_id, reason))

    def set_blocked(self, task_id: str, reason: str) -> None:
        pass

    def close(self, task_id: str, reason: str = "completed") -> None:
        pass

    def comment(self, task_id: str, body: str) -> None:
        pass

    def get(self, task_id: str) -> Task:
        return Task(
            id=task_id, title="Test", description=None, status=self._task_status
        )

    def list_ready(self, limit: int = 50) -> list[Task]:
        return []


class StubRateGauge:
    def __init__(self) -> None:
        self.updates: list[Event] = []

    def update(self, evt: Event) -> None:
        self.updates.append(evt)


def _make_runner(
    tmp_path: Path,
    argv: list[str],
    *,
    task_id: str = "t-001",
    task_status: str = "in_progress",
    config: RuntimeConfig | None = None,
    context_limit: int = 200_000,
) -> tuple[TaskRunner, StubQueue, StubRateGauge]:
    task = Task(
        id=task_id, title="Test task", description="Do the thing.", status="in_progress"
    )
    queue = StubQueue(task_status=task_status)
    gauge = StubRateGauge()
    runner = TaskRunner(
        task=task,
        coder=StubCoder(argv=argv, context_limit=context_limit),
        queue=queue,
        config=config or RuntimeConfig(),
        rate_gauge=gauge,
        project_root=tmp_path,
        fleet_home=tmp_path,
        log=structlog.get_logger(),
    )
    return runner, queue, gauge


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
    runner, _, _ = _make_runner(tmp_path, argv=[sys.executable, "-c", script])

    result = asyncio.run(runner.run())

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
    runner, _, _ = _make_runner(tmp_path, argv=[sys.executable, "-c", script])

    asyncio.run(runner.run())

    events_path = tmp_path / "tasks" / "t-001" / "events.jsonl"
    assert events_path.exists()
    records = [json.loads(line) for line in events_path.read_text().splitlines() if line.strip()]
    assert len(records) >= 1


def test_clean_exit_creates_task_dir(tmp_path: Path) -> None:
    runner, _, _ = _make_runner(
        tmp_path, argv=[sys.executable, "-c", "import sys; sys.exit(0)"]
    )

    asyncio.run(runner.run())

    assert (tmp_path / "tasks" / "t-001").is_dir()
    assert (tmp_path / "tasks" / "t-001" / "artifacts").is_dir()
    assert (tmp_path / "tasks" / "t-001" / "log.jsonl").exists()


def test_runner_creates_plan_and_status_and_knowledge_stubs(tmp_path: Path) -> None:
    runner, _, _ = _make_runner(
        tmp_path, argv=[sys.executable, "-c", "import sys; sys.exit(0)"]
    )

    asyncio.run(runner.run())

    artifacts_dir = tmp_path / "tasks" / "t-001" / "artifacts"
    plan = artifacts_dir / "PLAN_AND_STATUS.md"
    knowledge = artifacts_dir / "KNOWLEDGE.md"
    assert plan.exists(), "fleet must pre-create PLAN_AND_STATUS.md"
    assert knowledge.exists(), "fleet must pre-create KNOWLEDGE.md"
    plan_text = plan.read_text()
    knowledge_text = knowledge.read_text()
    assert "t-001" in plan_text
    assert "Status" in plan_text
    assert "t-001" in knowledge_text


def test_runner_does_not_overwrite_existing_stubs(tmp_path: Path) -> None:
    artifacts_dir = tmp_path / "tasks" / "t-001" / "artifacts"
    artifacts_dir.mkdir(parents=True)
    (artifacts_dir / "PLAN_AND_STATUS.md").write_text("custom plan content")
    (artifacts_dir / "KNOWLEDGE.md").write_text("custom knowledge content")

    runner, _, _ = _make_runner(
        tmp_path, argv=[sys.executable, "-c", "import sys; sys.exit(0)"]
    )

    asyncio.run(runner.run())

    assert (artifacts_dir / "PLAN_AND_STATUS.md").read_text() == "custom plan content"
    assert (artifacts_dir / "KNOWLEDGE.md").read_text() == "custom knowledge content"


def test_runner_calls_write_runtime_config_before_spawn(tmp_path: Path) -> None:
    """TaskRunner.run must call coder.write_runtime_config(project_root, task) before spawning."""
    task = Task(id="t-cfg", title="Config test", description=None, status="in_progress")
    coder = StubCoder(argv=[sys.executable, "-c", "import sys; sys.exit(0)"])
    runner = TaskRunner(
        task=task,
        coder=coder,
        queue=StubQueue(),
        config=RuntimeConfig(),
        rate_gauge=StubRateGauge(),
        project_root=tmp_path,
        fleet_home=tmp_path,
        log=structlog.get_logger(),
    )

    asyncio.run(runner.run())

    assert len(coder.runtime_config_calls) == 1
    called_project, called_task = coder.runtime_config_calls[0]
    assert called_project == tmp_path
    assert called_task is task


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
    runner, queue, _ = _make_runner(
        tmp_path,
        argv=[sys.executable, "-c", script],
    )

    result = asyncio.run(runner.run())

    assert result.outcome == TaskOutcome.RATE_LIMIT
    assert result.resets_at == 9999999999


def test_rate_limit_calls_queue_release(tmp_path: Path) -> None:
    rate_event = json.dumps(
        {"api_error_status": 429, "error": "rate_limit", "resetsAt": 9999999999}
    )
    script = (
        "import sys, time\n"
        f"sys.stdout.write({rate_event!r} + '\\n')\n"
        "sys.stdout.flush()\n"
        "time.sleep(60)\n"
    )
    runner, queue, _ = _make_runner(
        tmp_path,
        argv=[sys.executable, "-c", script],
    )

    asyncio.run(runner.run())

    assert len(queue.released) == 1
    task_id, reason = queue.released[0]
    assert task_id == "t-001"
    assert "rate_limit" in reason
    assert "9999999999" in reason


def test_rate_limit_no_resets_at_gives_none(tmp_path: Path) -> None:
    rate_event = json.dumps({"api_error_status": 429, "error": "rate_limit"})
    script = (
        "import sys, time\n"
        f"sys.stdout.write({rate_event!r} + '\\n')\n"
        "sys.stdout.flush()\n"
        "time.sleep(60)\n"
    )
    runner, queue, _ = _make_runner(tmp_path, argv=[sys.executable, "-c", script])

    result = asyncio.run(runner.run())

    assert result.outcome == TaskOutcome.RATE_LIMIT
    assert result.resets_at is None
    assert len(queue.released) == 1


# ---------------------------------------------------------------------------
# Test: Context-pressure flag → CONTEXT_PRESSURE + flag removed
# ---------------------------------------------------------------------------

_CP_SCRIPT = (
    "import sys, os\n"
    "from pathlib import Path\n"
    "p = Path(os.environ['FLEET_TASK_DIR'])\n"
    "p.mkdir(parents=True, exist_ok=True)\n"
    "(p / '.context_pressure').touch()\n"
    "sys.exit(0)\n"
)


def test_context_pressure_returns_context_pressure(tmp_path: Path) -> None:
    runner, _, _ = _make_runner(tmp_path, argv=[sys.executable, "-c", _CP_SCRIPT])

    result = asyncio.run(runner.run())

    assert result.outcome == TaskOutcome.CONTEXT_PRESSURE
    assert result.exit_code == 0


def test_context_pressure_flag_is_removed(tmp_path: Path) -> None:
    runner, _, _ = _make_runner(tmp_path, argv=[sys.executable, "-c", _CP_SCRIPT])

    asyncio.run(runner.run())

    cp_flag = tmp_path / "tasks" / "t-001" / ".context_pressure"
    assert not cp_flag.exists()


def test_context_pressure_wins_over_rc0(tmp_path: Path) -> None:
    runner, _, _ = _make_runner(tmp_path, argv=[sys.executable, "-c", _CP_SCRIPT])

    result = asyncio.run(runner.run())

    assert result.outcome == TaskOutcome.CONTEXT_PRESSURE


# ---------------------------------------------------------------------------
# Test: Non-zero rc → FAILURE + stderr_tail
# ---------------------------------------------------------------------------


def test_nonzero_rc_returns_failure(tmp_path: Path) -> None:
    script = (
        "import sys\n"
        "sys.stderr.write('something went wrong\\n')\n"
        "sys.stderr.flush()\n"
        "sys.exit(1)\n"
    )
    runner, _, _ = _make_runner(tmp_path, argv=[sys.executable, "-c", script])

    result = asyncio.run(runner.run())

    assert result.outcome == TaskOutcome.FAILURE
    assert result.exit_code == 1


def test_nonzero_rc_populates_stderr_tail(tmp_path: Path) -> None:
    script = (
        "import sys\n"
        "sys.stderr.write('something went wrong\\n')\n"
        "sys.stderr.flush()\n"
        "sys.exit(1)\n"
    )
    runner, _, _ = _make_runner(tmp_path, argv=[sys.executable, "-c", script])

    result = asyncio.run(runner.run())

    assert result.stderr_tail is not None
    assert "something went wrong" in result.stderr_tail


# ---------------------------------------------------------------------------
# Test: cancel() → SIGKILL escalation when child ignores SIGTERM
# ---------------------------------------------------------------------------


def test_cancel_sigkill_escalation(tmp_path: Path) -> None:
    script = (
        "import signal, time\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "time.sleep(60)\n"
    )
    runner, _, _ = _make_runner(
        tmp_path,
        argv=[sys.executable, "-c", script],
    )

    async def _run() -> None:
        run_task = asyncio.create_task(runner.run())
        await asyncio.sleep(0.3)
        await runner.cancel()
        result = await run_task
        assert result.outcome == TaskOutcome.FAILURE
        assert result.reason == "supervisor_shutdown"

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# Test: BEADS_DIR injection
# ---------------------------------------------------------------------------


def test_beads_dir_injected_into_subprocess(tmp_path: Path) -> None:
    """Agent subprocess receives BEADS_DIR ending with '.beads'."""
    beads_dir = str(tmp_path / ".beads")
    script = (
        "import os, sys\n"
        f"sys.exit(0 if os.environ.get('BEADS_DIR','') == {beads_dir!r} else 3)\n"
    )
    runner, _, _ = _make_runner(tmp_path, argv=[sys.executable, "-c", script])

    result = asyncio.run(runner.run())

    assert result.outcome == TaskOutcome.SUCCESS
    assert result.exit_code == 0


class _BeadsDirCoder(StubCoder):
    """StubCoder that returns an explicit BEADS_DIR in env."""

    def env(self, task: Task, task_dir: Path) -> dict[str, str]:
        env = super().env(task, task_dir)
        env["BEADS_DIR"] = "/custom/.beads"
        return env


def test_subprocess_sees_coder_provided_beads_dir(tmp_path: Path) -> None:
    """When coder provides BEADS_DIR, TaskRunner must not override it."""
    script = (
        "import os, sys\n"
        "sys.exit(0 if os.environ.get('BEADS_DIR') == '/custom/.beads' else 3)\n"
    )
    task = Task(id="t-002", title="Test task", description=None, status="in_progress")
    coder = _BeadsDirCoder(argv=[sys.executable, "-c", script])
    runner = TaskRunner(
        task=task,
        coder=coder,
        queue=StubQueue(),
        config=RuntimeConfig(),
        rate_gauge=StubRateGauge(),
        project_root=tmp_path,
        fleet_home=tmp_path,
        log=structlog.get_logger(),
    )

    result = asyncio.run(runner.run())

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
    runner = TaskRunner(
        task=task,
        coder=coder,
        queue=StubQueue(),
        config=RuntimeConfig(),
        rate_gauge=StubRateGauge(),
        project_root=tmp_path,
        fleet_home=tmp_path,
        log=structlog.get_logger(),
    )

    result = asyncio.run(runner.run())

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
    runner = TaskRunner(
        task=task,
        coder=coder,
        queue=StubQueue(),
        config=RuntimeConfig(),
        rate_gauge=StubRateGauge(),
        project_root=tmp_path,
        fleet_home=tmp_path,
        log=structlog.get_logger(),
    )

    asyncio.run(runner.run())

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
    runner, _, _ = _make_runner(
        tmp_path,
        argv=[sys.executable, "-c", clean_script],
        context_limit=1_000,
    )

    result = asyncio.run(runner.run())

    assert result.outcome == TaskOutcome.SUCCESS
    log_path = tmp_path / "tasks" / "t-001" / "log.jsonl"
    log_records = [
        json.loads(line) for line in log_path.read_text().splitlines() if line.strip()
    ]
    context_usage_events = [r for r in log_records if r.get("event") == "context_usage"]
    # The first usage at 101 (pct=10.1 -> bucket=1) logs, the second at 201 (pct=20.1 -> bucket=2) logs.
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
    runner, _, _ = _make_runner(
        tmp_path,
        argv=[sys.executable, "-c", clean_script],
        context_limit=1_000,
    )

    result = asyncio.run(runner.run())

    assert result.outcome == TaskOutcome.SUCCESS
    log_path = tmp_path / "tasks" / "t-001" / "log.jsonl"
    log_records = [
        json.loads(line) for line in log_path.read_text().splitlines() if line.strip()
    ]
    context_usage_events = [r for r in log_records if r.get("event") == "context_usage"]
    # Both are in 10-19% range (bucket=1), so only one log line.
    assert len(context_usage_events) == 1


# ---------------------------------------------------------------------------
# Test: spawn uses start_new_session (own process group)
# ---------------------------------------------------------------------------


def test_spawn_uses_new_session(tmp_path: Path, monkeypatch) -> None:
    """TaskRunner.run must spawn the coder with start_new_session=True."""
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

    runner, _, _ = _make_runner(
        tmp_path, argv=[sys.executable, "-c", "import sys; sys.exit(0)"]
    )

    result = asyncio.run(runner.run())

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
    import fleet.runner as runner_mod

    monkeypatch.setattr(runner_mod, "PROBE_INTERVAL_SEC", 0.01)
    monkeypatch.setattr(runner_mod, "PROBE_SILENCE_SEC", -1)

    class _FakeStdout:
        _limit = 0

        async def readline(self) -> bytes:
            await asyncio.sleep(3600)
            return b""

    class _FakeProc:
        pid = 987654
        returncode: int | None = None
        stdout = _FakeStdout()

        def send_signal(self, sig) -> None:
            self.returncode = -sig

        async def wait(self) -> int:
            return self.returncode if self.returncode is not None else 0

    async def _fake_create(*args, **kwargs):
        return _FakeProc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_create)

    from fleet.schemas import TaskOutcomeRecord

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

    task = Task(
        id="t-probe", title="Test task", description="Do the thing.", status="in_progress"
    )
    queue = StubQueue()
    gauge = StubRateGauge()
    coder = FakeProbeCoder(argv=[sys.executable, "-c", "pass"])
    runner = TaskRunner(
        task=task,
        coder=coder,
        queue=queue,
        config=RuntimeConfig(),
        rate_gauge=gauge,
        project_root=tmp_path,
        fleet_home=tmp_path,
        log=structlog.get_logger(),
    )

    result = asyncio.run(asyncio.wait_for(runner.run(), timeout=10.0))

    assert coder.probe_calls >= 2
    assert result.outcome == TaskOutcome.RATE_LIMIT
    assert result.reason == "opencode provider rate limit"
