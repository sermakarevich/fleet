import asyncio
import json
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
        return Task(id=task_id, title="Test", description=None, status=self._task_status)

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
    task = Task(id=task_id, title="Test task", description="Do the thing.", status="in_progress")
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
    lines = [l for l in (FIXTURES / "stream_clean_exit.jsonl").read_text().splitlines() if l.strip()]
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
    lines = [l for l in (FIXTURES / "stream_clean_exit.jsonl").read_text().splitlines() if l.strip()]
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
    records = [json.loads(l) for l in events_path.read_text().splitlines() if l.strip()]
    assert len(records) >= 1


def test_clean_exit_creates_task_dir(tmp_path: Path) -> None:
    runner, _, _ = _make_runner(tmp_path, argv=[sys.executable, "-c", "import sys; sys.exit(0)"])

    asyncio.run(runner.run())

    assert (tmp_path / "tasks" / "t-001").is_dir()
    assert (tmp_path / "tasks" / "t-001" / "artifacts").is_dir()
    assert (tmp_path / "tasks" / "t-001" / "log.jsonl").exists()


def test_runner_creates_plan_and_status_and_knowledge_stubs(tmp_path: Path) -> None:
    runner, _, _ = _make_runner(tmp_path, argv=[sys.executable, "-c", "import sys; sys.exit(0)"])

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

    runner, _, _ = _make_runner(tmp_path, argv=[sys.executable, "-c", "import sys; sys.exit(0)"])

    asyncio.run(runner.run())

    assert (artifacts_dir / "PLAN_AND_STATUS.md").read_text() == "custom plan content"
    assert (artifacts_dir / "KNOWLEDGE.md").read_text() == "custom knowledge content"


# ---------------------------------------------------------------------------
# Test: Rate-limit rejection → RATE_LIMIT + queue.release
# ---------------------------------------------------------------------------

def test_rate_limit_rejection_returns_rate_limit(tmp_path: Path) -> None:
    rate_event = json.dumps({"api_error_status": 429, "error": "rate_limit", "resetsAt": 9999999999})
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
    rate_event = json.dumps({"api_error_status": 429, "error": "rate_limit", "resetsAt": 9999999999})
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
# Test: Context pressure from usage (works for any coder emitting usage data)
# ---------------------------------------------------------------------------

def _usage_script(input_tokens: int) -> str:
    """Script that emits one assistant event with the given input_tokens then sleeps."""
    event = json.dumps({
        "type": "assistant",
        "message": {"content": [], "usage": {"input_tokens": input_tokens}},
        "session_id": "s-ctx",
    })
    return (
        "import sys\n"
        f"sys.stdout.write({event!r} + '\\n')\n"
        "sys.stdout.flush()\n"
        "import time; time.sleep(60)\n"
    )


def test_context_pressure_from_usage_returns_context_pressure(tmp_path: Path) -> None:
    """Runner signals CONTEXT_PRESSURE when usage exceeds context_limit * threshold."""
    runner, _, _ = _make_runner(
        tmp_path,
        argv=[sys.executable, "-c", _usage_script(950)],
        config=RuntimeConfig(context_pressure_threshold_pct=90),
        context_limit=1_000,  # threshold = 900; 950 >= 900 → context pressure
    )

    result = asyncio.run(runner.run())

    assert result.outcome == TaskOutcome.CONTEXT_PRESSURE


def test_context_pressure_from_usage_flag_removed(tmp_path: Path) -> None:
    """Runner removes the .context_pressure flag after detecting it from usage."""
    runner, _, _ = _make_runner(
        tmp_path,
        argv=[sys.executable, "-c", _usage_script(950)],
        config=RuntimeConfig(context_pressure_threshold_pct=90),
        context_limit=1_000,
    )

    asyncio.run(runner.run())

    cp_flag = tmp_path / "tasks" / "t-001" / ".context_pressure"
    assert not cp_flag.exists()


def test_context_pressure_from_usage_not_triggered_below_threshold(tmp_path: Path) -> None:
    """Usage below threshold does not trigger context pressure; process exits normally."""
    runner, _, _ = _make_runner(
        tmp_path,
        argv=[sys.executable, "-c", _usage_script(800)],
        config=RuntimeConfig(context_pressure_threshold_pct=90),
        context_limit=1_000,  # threshold = 900; 800 < 900 → no context pressure
    )

    # The script would sleep indefinitely if not terminated, but for this test we
    # use a script that exits cleanly after emitting low-usage events.
    clean_script = (
        "import sys, json\n"
        f"event = json.dumps({{'type': 'assistant', 'message': {{'content': [], 'usage': {{'input_tokens': 800}}}}, 'session_id': 's1'}})\n"
        "sys.stdout.write(event + '\\n')\n"
        "sys.stdout.flush()\n"
        "sys.exit(0)\n"
    )
    runner, _, _ = _make_runner(
        tmp_path,
        argv=[sys.executable, "-c", clean_script],
        config=RuntimeConfig(context_pressure_threshold_pct=90),
        context_limit=1_000,
    )

    result = asyncio.run(runner.run())

    assert result.outcome == TaskOutcome.SUCCESS


def test_context_pressure_from_usage_uses_coder_context_limit(tmp_path: Path) -> None:
    """Threshold scales with coder.context_limit; same token count triggers at 1k but not 200k."""
    # 950 tokens: triggers at limit=1_000 (threshold=900) but not at limit=200_000
    clean_script = (
        "import sys, json\n"
        "event = json.dumps({'type': 'assistant', 'message': {'content': [], 'usage': {'input_tokens': 950}}, 'session_id': 's1'})\n"
        "sys.stdout.write(event + '\\n')\n"
        "sys.stdout.flush()\n"
        "sys.exit(0)\n"
    )
    runner, _, _ = _make_runner(
        tmp_path,
        argv=[sys.executable, "-c", clean_script],
        config=RuntimeConfig(context_pressure_threshold_pct=90),
        context_limit=200_000,  # threshold = 180_000; 950 is nowhere near → SUCCESS
    )

    result = asyncio.run(runner.run())

    assert result.outcome == TaskOutcome.SUCCESS
