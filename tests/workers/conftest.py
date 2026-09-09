"""Shared fixtures and helpers for worker tests."""

from __future__ import annotations

import asyncio
from pathlib import Path

import structlog

from fleet.coders.claude import ClaudeCoder
from fleet.core.config import RuntimeConfig
from fleet.core.task import Event, Task, TaskOutcomeRecord
from fleet.state.paths import task_dir
from fleet.workers.base import StepContext, StepStatus
from fleet.workers.llm_session import LlmSession
from tests.workers.fake_runner import FakeProcess, FakeProcessRunner

# ---------------------------------------------------------------------------
# Shared by test_llm_session.py splits (Clean 29/30: moved, not rewritten).
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


def _run(session: LlmSession, ctx: StepContext) -> TaskOutcomeRecord:
    step_result = asyncio.run(session.run(ctx))
    assert step_result.status == StepStatus.OUTCOME
    assert step_result.outcome is not None
    return step_result.outcome
