"""Tests for LlmSession exit outcomes (unit under test: workers/session success/failure paths)."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from fleet.core.task import TaskOutcome
from tests.workers.conftest import _make_session, _run
from tests.workers.fake_runner import FakeProcess

FIXTURES = Path(__file__).parent.parent / "fixtures"


def _fixture_lines(name: str) -> list[str]:
    return [line for line in (FIXTURES / name).read_text().splitlines() if line.strip()]


def _rate_limit_proc() -> FakeProcess:
    rate_event = json.dumps(
        {"api_error_status": 429, "error": "rate_limit", "resetsAt": 9999999999}
    )
    return FakeProcess(lines=[rate_event], hang=True)


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
