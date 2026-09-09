"""Tests for LlmSession env and event logging (unit under test: workers/session env/LogWriter)."""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

from fleet.core.task import Event, Task, TaskOutcome
from fleet.workers.llm_session import LlmSession
from tests.workers.conftest import StubCoder, _make_ctx, _make_session, _run
from tests.workers.fake_runner import FakeProcess, FakeProcessRunner


class _BeadsDirCoder(StubCoder):
    """StubCoder that returns an explicit BEADS_DIR in env."""

    def env(self, task: Task, task_dir: Path) -> dict[str, str]:
        env = super().env(task, task_dir)
        env["BEADS_DIR"] = "/custom/.beads"
        return env


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


def _usage_line(input_tokens: int) -> str:
    return json.dumps(
        {
            "type": "assistant",
            "message": {"content": [], "usage": {"input_tokens": input_tokens}},
            "session_id": "s-ctx",
        }
    )


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


def test_subprocess_sees_coder_provided_beads_dir(tmp_path: Path) -> None:
    """When coder provides BEADS_DIR, LlmSession must not override it."""
    task = Task(id="t-002", title="Test task", description=None, status="in_progress")
    runner = FakeProcessRunner([FakeProcess()])
    ctx = _make_ctx(tmp_path, task, _BeadsDirCoder(argv=[sys.executable, "-c", "pass"]), runner)

    result = _run(LlmSession(), ctx)

    assert result.outcome == TaskOutcome.SUCCESS
    assert runner.last_env["BEADS_DIR"] == "/custom/.beads"


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
