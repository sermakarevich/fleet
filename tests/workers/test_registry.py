from pathlib import Path

import pytest
import structlog

from fleet.core.config import RuntimeConfig
from fleet.core.task import Task
from fleet.state.paths import task_dir as _task_dir_path
from fleet.workers import select_worker
from fleet.workers.base import StepContext
from fleet.workers.task import FreshTask


def _ctx(tmp_path: Path, task_id: str = "t-001") -> StepContext:
    return StepContext(
        task=Task(id=task_id, title="t", description=None, status="in_progress"),
        task_dir=_task_dir_path(tmp_path, task_id),
        project_root=tmp_path,
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

    worker = select_worker(task, ctx)

    assert worker.name == FreshTask.name


def test_metadata_worker_override_wins_over_type(tmp_path: Path) -> None:
    task = Task(
        id="t-001", title="t", description=None, status="in_progress", type="epic", worker="task"
    )
    ctx = _ctx(tmp_path)

    worker = select_worker(task, ctx)

    assert worker.name == FreshTask.name


def test_unknown_family_raises_value_error(tmp_path: Path) -> None:
    task = Task(id="t-001", title="t", description=None, status="in_progress", worker="nope")
    ctx = _ctx(tmp_path)

    with pytest.raises(ValueError, match="nope"):
        select_worker(task, ctx)


def test_epic_type_routes_to_observer_family(tmp_path: Path) -> None:
    task = Task(id="t-001", title="t", description=None, status="in_progress", type="epic")
    ctx = _ctx(tmp_path)

    worker = select_worker(task, ctx)

    assert worker.name == "observer"
