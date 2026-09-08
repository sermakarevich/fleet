import asyncio
from pathlib import Path

import structlog

from fleet.core.config import RuntimeConfig
from fleet.core.task import Task
from fleet.state.paths import task_dir as _task_dir_path
from fleet.workers.base import StepContext
from fleet.workers.llm_session import LlmSession
from fleet.workers.task import FreshTask, PrepareArtifacts, plan_task


class StubCoder:
    name = "stub"
    context_limit = 200_000

    def __init__(self) -> None:
        self.runtime_config_calls: list[tuple[Path, Task]] = []

    def write_runtime_config(self, project: Path, task: Task) -> None:
        self.runtime_config_calls.append((project, task))


def _ctx(tmp_path: Path, task_id: str = "t-001") -> StepContext:
    task = Task(id=task_id, title="Test task", description="Do the thing.", status="in_progress")
    return StepContext(
        task=task,
        task_dir=_task_dir_path(tmp_path, task_id),
        project_root=tmp_path,
        fleet_home=tmp_path,
        coder=StubCoder(),
        config=RuntimeConfig(),
        rate_gauge=None,  # type: ignore[arg-type]
        log=structlog.get_logger(),
    )


def test_prepare_artifacts_creates_stubs(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)

    result = asyncio.run(PrepareArtifacts().run(ctx))

    assert result.status == "ok"
    artifacts_dir = ctx.task_dir / "artifacts"
    plan = artifacts_dir / "PLAN.md"
    handoff = artifacts_dir / "HANDOFF.md"
    knowledge = artifacts_dir / "KNOWLEDGE.md"
    assert plan.exists()
    assert handoff.exists()
    assert knowledge.exists()
    assert (artifacts_dir / "outputs").is_dir()
    assert "t-001" in plan.read_text()
    assert "Next" in handoff.read_text()
    assert "t-001" in knowledge.read_text()


def test_prepare_artifacts_does_not_overwrite_existing_stubs(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    artifacts_dir = ctx.task_dir / "artifacts"
    artifacts_dir.mkdir(parents=True)
    (artifacts_dir / "PLAN.md").write_text("custom plan content")
    (artifacts_dir / "HANDOFF.md").write_text("custom handoff content")
    (artifacts_dir / "KNOWLEDGE.md").write_text("custom knowledge content")

    asyncio.run(PrepareArtifacts().run(ctx))

    assert (artifacts_dir / "PLAN.md").read_text() == "custom plan content"
    assert (artifacts_dir / "HANDOFF.md").read_text() == "custom handoff content"
    assert (artifacts_dir / "KNOWLEDGE.md").read_text() == "custom knowledge content"


def test_prepare_artifacts_rotates_previous_result_json(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    artifacts_dir = ctx.task_dir / "artifacts"
    artifacts_dir.mkdir(parents=True)
    (artifacts_dir / "RESULT.json").write_text('{"schema": 1, "status": "partial"}')

    asyncio.run(PrepareArtifacts().run(ctx))

    assert not (artifacts_dir / "RESULT.json").exists()
    assert (artifacts_dir / "RESULT.prev.json").read_text() == '{"schema": 1, "status": "partial"}'


def test_prepare_artifacts_calls_write_runtime_config(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, task_id="t-cfg")

    asyncio.run(PrepareArtifacts().run(ctx))

    coder = ctx.coder
    assert isinstance(coder, StubCoder)
    assert len(coder.runtime_config_calls) == 1
    called_project, called_task = coder.runtime_config_calls[0]
    assert called_project == tmp_path
    assert called_task is ctx.task


def test_plan_task_returns_fresh_task_shaped_worker(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)

    worker = plan_task(ctx)

    assert worker.name == FreshTask.name == "task.fresh"
    assert [type(s) for s in worker.steps] == [PrepareArtifacts, LlmSession]


def test_plan_task_builds_fresh_step_instances(tmp_path: Path) -> None:
    """Each call must build fresh step instances: LlmSession keeps per-attempt
    subprocess state on self, and worker runs execute concurrently across tasks."""
    ctx = tmp_path
    worker_a = plan_task(_ctx(ctx, "t-a"))
    worker_b = plan_task(_ctx(ctx, "t-b"))

    assert worker_a.steps[1] is not worker_b.steps[1]
