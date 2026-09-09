import asyncio
import json
from pathlib import Path

import structlog

from fleet.core.config import RuntimeConfig
from fleet.core.task import Task
from fleet.state.paths import task_dir as _task_dir_path
from fleet.workers.base import FnStep, StepContext, StepStatus
from fleet.workers.llm_session import LlmSession
from fleet.workers.task import PREPARE_ARTIFACTS, FreshTask, plan_task


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
    ctx.attempt_dir = ctx.task_dir / "attempts" / "1"
    ctx.attempt_n = 1

    result = asyncio.run(PREPARE_ARTIFACTS.run(ctx))

    assert result.status == StepStatus.OK
    state = ctx.task_dir / "STATE.md"
    assert state.exists()
    assert (ctx.task_dir / "outputs").is_dir()
    assert "t-001" in state.read_text()
    assert "## Next" in state.read_text()
    # Launch decision recorded in run.json, not launch.json.
    run = json.loads((ctx.attempt_dir / "run.json").read_text(encoding="utf-8"))
    assert run["launch"]["mode"] == "fresh"
    assert not (ctx.attempt_dir / "launch.json").exists()


def test_prepare_artifacts_does_not_overwrite_existing_state(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    ctx.task_dir.mkdir(parents=True)
    (ctx.task_dir / "STATE.md").write_text("custom state content")

    asyncio.run(PREPARE_ARTIFACTS.run(ctx))

    assert (ctx.task_dir / "STATE.md").read_text() == "custom state content"


def test_prepare_artifacts_leaves_previous_result_json_alone(tmp_path: Path) -> None:
    """No rotation: reap snapshots STATE.md/RESULT.json and unlinks the live file."""
    ctx = _ctx(tmp_path)
    ctx.task_dir.mkdir(parents=True)
    (ctx.task_dir / "RESULT.json").write_text('{"schema": 1, "status": "partial"}')

    asyncio.run(PREPARE_ARTIFACTS.run(ctx))

    assert (ctx.task_dir / "RESULT.json").read_text() == '{"schema": 1, "status": "partial"}'


def test_prepare_artifacts_calls_write_runtime_config(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, task_id="t-cfg")

    asyncio.run(PREPARE_ARTIFACTS.run(ctx))

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
    assert [type(s) for s in worker.steps] == [FnStep, LlmSession]


def test_plan_task_builds_fresh_step_instances(tmp_path: Path) -> None:
    """Each call must build fresh step instances: LlmSession keeps per-attempt
    subprocess state on self, and worker runs execute concurrently across tasks."""
    ctx = tmp_path
    worker_a = plan_task(_ctx(ctx, "t-a"))
    worker_b = plan_task(_ctx(ctx, "t-b"))

    assert worker_a.steps[1] is not worker_b.steps[1]
