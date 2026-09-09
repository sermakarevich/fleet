from pathlib import Path

import pytest
import structlog

from fleet.core.config import RuntimeConfig
from fleet.core.task import Task
from fleet.state.paths import task_dir
from fleet.workers import select_worker
from fleet.workers.base import StepContext
from fleet.workers.task_family import FreshTask
from tests.conftest import FakeQueue


def _ctx(tmp_path: Path, task_id: str = "t-001") -> StepContext:
    return StepContext(
        task=Task(id=task_id, title="t", description=None, status="in_progress"),
        task_dir=task_dir(tmp_path, task_id),
        workdir=tmp_path,
        fleet_home=tmp_path,
        coder=None,
        config=RuntimeConfig(),
        rate_gauge=None,  # type: ignore[arg-type]
        log=structlog.get_logger(),
    )


@pytest.mark.parametrize("task_type", ["task", "bug", "feature", "chore", None])
def test_type_routes_to_task_family(tmp_path: Path, task_type: str | None) -> None:
    task = Task(id="t-001", title="t", description=None, status="in_progress", type=task_type)
    ctx = _ctx(tmp_path)

    worker = select_worker(task, ctx, FakeQueue())

    assert worker.name == FreshTask.name


def test_metadata_worker_override_wins_over_type(tmp_path: Path) -> None:
    task = Task(
        id="t-001", title="t", description=None, status="in_progress", type="epic", worker="task"
    )
    ctx = _ctx(tmp_path)

    worker = select_worker(task, ctx, FakeQueue())

    assert worker.name == FreshTask.name


def test_unknown_family_raises_value_error(tmp_path: Path) -> None:
    task = Task(id="t-001", title="t", description=None, status="in_progress", worker="nope")
    ctx = _ctx(tmp_path)

    with pytest.raises(ValueError, match="nope"):
        select_worker(task, ctx, FakeQueue())


def test_epic_type_routes_to_observer_family(tmp_path: Path) -> None:
    task = Task(id="t-001", title="t", description=None, status="in_progress", type="epic")
    ctx = _ctx(tmp_path)

    worker = select_worker(task, ctx, FakeQueue())

    assert worker.name == "observer"


def test_job_family_receives_queue_and_store(tmp_path: Path) -> None:
    """The factory threads the queue into job steps (no module builds one)."""
    task = Task(id="t-001", title="t", description=None, status="in_progress", worker="job")
    ctx = _ctx(tmp_path)
    queue = FakeQueue()

    worker = select_worker(task, ctx, queue)

    assert worker.name == "job.research"
    assert worker.steps[0].name == "job_prepare"
