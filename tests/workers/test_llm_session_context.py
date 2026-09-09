"""Tests for LlmSession context checkpoint (75%) and kill (90%) behaviour."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import structlog

from fleet.coders.claude import ClaudeCoder
from fleet.core.config import RuntimeConfig
from fleet.core.task import Event, Task, TaskOutcome
from fleet.state import paths as state_paths
from fleet.workers.base import StepContext, StepStatus
from fleet.workers.llm_session import LlmSession
from fleet.workers.session.classify import error_text_of, is_context_error_text
from tests.workers.fake_runner import FakeProcess, FakeProcessRunner


class StubCoder:
    name = "stub"
    context_limit: int = 1_000

    def __init__(self) -> None:
        self._cli = ClaudeCoder(fleet_home=Path.cwd())
        self.model = "stub-model"

    @classmethod
    def context_limit_for(cls, model: str | None, overrides: dict[str, int] | None = None) -> int:
        return cls.context_limit

    def build_argv(self, task: Task, task_dir: Path, plan=None) -> list[str]:
        return ["fake-coder"]

    def env(self, task: Task, task_dir: Path) -> dict[str, str]:
        return {
            "FLEET_TASK_ID": task.id,
            "FLEET_TASK_DIR": str(task_dir),
        }

    def normalize_event(self, raw_line: str) -> Event | None:
        return self._cli.normalize_event(raw_line)


class _Gauge:
    def update(self, event: Event) -> None:
        return None


def _ctx(
    tmp_path: Path, lines: list[str], task_id: str = "t-ctx", exit_code: int | None = 0
) -> StepContext:
    task = Task(id=task_id, title="T", description=None, status="in_progress")
    task_dir = state_paths.task_dir(tmp_path, task_id)
    attempt_dir = task_dir / "attempts" / "1"
    hang = exit_code is None
    return StepContext(
        task=task,
        task_dir=task_dir,
        workdir=tmp_path,
        fleet_home=tmp_path,
        coder=StubCoder(),
        config=RuntimeConfig(),
        rate_gauge=_Gauge(),  # type: ignore[arg-type]
        log=structlog.get_logger(),
        attempt_dir=attempt_dir,
        attempt_n=1,
        runner=FakeProcessRunner([FakeProcess(lines=lines, exit_code=exit_code, hang=hang)]),
    )


def _stderr_ctx(tmp_path: Path, stderr_text: str, task_id: str = "t-stderr") -> StepContext:
    task = Task(id=task_id, title="T", description=None, status="in_progress")
    task_dir = state_paths.task_dir(tmp_path, task_id)
    attempt_dir = task_dir / "attempts" / "1"
    return StepContext(
        task=task,
        task_dir=task_dir,
        workdir=tmp_path,
        fleet_home=tmp_path,
        coder=StubCoder(),
        config=RuntimeConfig(),
        rate_gauge=_Gauge(),  # type: ignore[arg-type]
        log=structlog.get_logger(),
        attempt_dir=attempt_dir,
        attempt_n=1,
        runner=FakeProcessRunner(
            [FakeProcess(exit_code=1, stderr_text=stderr_text)],
        ),
    )


def _run(session: LlmSession, ctx: StepContext):
    step_result = asyncio.run(session.run(ctx))
    assert step_result.status == StepStatus.OUTCOME
    assert step_result.outcome is not None
    return step_result.outcome


def _usage_line(input_tokens: int) -> str:
    return json.dumps(
        {
            "type": "assistant",
            "message": {"content": [], "usage": {"input_tokens": input_tokens}},
            "session_id": "s-ctx",
        }
    )


def test_checkpoint_marker_written_at_75_pct(tmp_path: Path) -> None:
    """80% of limit: .checkpoint_requested appears, session still succeeds."""
    ctx = _ctx(tmp_path, [_usage_line(800)])

    result = _run(LlmSession(), ctx)

    assert result.outcome == TaskOutcome.SUCCESS
    assert (ctx.attempt_dir / ".checkpoint_requested").exists()


def test_no_checkpoint_below_threshold(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, [_usage_line(100)])

    result = _run(LlmSession(), ctx)

    assert result.outcome == TaskOutcome.SUCCESS
    assert not (ctx.attempt_dir / ".checkpoint_requested").exists()


def test_kill_at_90_pct_reports_context_pressure(tmp_path: Path) -> None:
    """95% of limit: process group killed, outcome is CONTEXT_PRESSURE."""
    proc_lines = [_usage_line(950)]
    ctx = _ctx(tmp_path, proc_lines, exit_code=None)

    result = _run(LlmSession(), ctx)

    assert result.outcome == TaskOutcome.CONTEXT_PRESSURE
    assert "kill" in result.reason
    assert (ctx.attempt_dir / ".checkpoint_requested").exists()


def test_stderr_context_error_reports_context_pressure(tmp_path: Path) -> None:
    ctx = _stderr_ctx(tmp_path, "Error: prompt is too long\n")

    result = _run(LlmSession(), ctx)

    assert result.outcome == TaskOutcome.CONTEXT_PRESSURE
    assert result.reason == "cli reported context overflow"


def test_event_context_error_reports_context_pressure(tmp_path: Path) -> None:
    line = json.dumps({"type": "system", "subtype": "error", "message": "Prompt is too long"})
    ctx = _ctx(tmp_path, [line], exit_code=None)

    result = _run(LlmSession(), ctx)

    assert result.outcome == TaskOutcome.CONTEXT_PRESSURE


def _done_line(payload: dict) -> str:
    return json.dumps(payload)


def test_assistant_prose_about_context_window_is_not_an_overflow(tmp_path: Path) -> None:
    """Regression: bead 5b was killed three times because the model *said*
    "Doing per-model context windows" and the scanner treated it as an error."""
    line = json.dumps(
        {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "text",
                        "text": "Doing per-model context windows - the token limit map next.",
                    }
                ]
            },
        }
    )
    done = _done_line({"type": "result", "subtype": "success", "is_error": False, "result": "ok"})
    ctx = _ctx(tmp_path, [line, done])

    result = _run(LlmSession(), ctx)

    assert result.outcome != TaskOutcome.CONTEXT_PRESSURE


def test_successful_result_mentioning_context_window_is_not_an_overflow(tmp_path: Path) -> None:
    done = _done_line(
        {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "result": "Added a context window map per model.",
        }
    )
    ctx = _ctx(tmp_path, [done])

    result = _run(LlmSession(), ctx)

    assert result.outcome != TaskOutcome.CONTEXT_PRESSURE


def test_failed_result_with_context_error_reports_context_pressure(tmp_path: Path) -> None:
    done = _done_line(
        {
            "type": "result",
            "subtype": "error",
            "is_error": True,
            "result": "Prompt is too long: 1050000 tokens > 1048576 maximum",
        }
    )
    ctx = _ctx(tmp_path, [done], exit_code=None)

    result = _run(LlmSession(), ctx)

    assert result.outcome == TaskOutcome.CONTEXT_PRESSURE


def test_error_text_of_ignores_prose_and_keeps_errors() -> None:
    class E:
        def __init__(self, kind, raw):
            self.kind, self.raw = kind, raw

    assert error_text_of(E("assistant_text", {"message": "context window"})) == ""
    assert error_text_of(E("session_ended", {"is_error": False, "result": "context window"})) == ""
    assert "context window" in error_text_of(
        E("session_ended", {"is_error": True, "result": "context window exceeded"})
    )
    assert "too long" in error_text_of(E("error", {"message": "prompt is too long"}))


def test_is_context_error_text() -> None:
    assert is_context_error_text("Error: prompt is too long")
    assert is_context_error_text("Maximum context length exceeded")
    assert not is_context_error_text("something went wrong")
    assert not is_context_error_text("")
