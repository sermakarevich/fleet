from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import structlog

from fleet.beads.queue import BeadsQueue
from fleet.core.config import RuntimeConfig
from fleet.core.task import Task
from fleet.orchestrator.checks import StartupCheck
from fleet.orchestrator.service import Service
from fleet.orchestrator.state import RunningWorker
from fleet.orchestrator.supervisor import Supervisor


@pytest.fixture
def queue(tmp_path: Path) -> BeadsQueue:
    return BeadsQueue(repo_root=tmp_path)


def make_supervisor(
    tmp_path: Path,
    *,
    config: RuntimeConfig | None = None,
    queue: BeadsQueue | None = None,
    services: list[Service] | None = None,
    checks: list[StartupCheck] | None = None,
) -> Supervisor:
    """Build a Supervisor over a minimal runtime.toml for tests."""
    runtime_toml = tmp_path / "runtime.toml"
    if not runtime_toml.exists():
        runtime_toml.write_text("max_concurrent = 3\n", encoding="utf-8")
    sup = Supervisor(
        queue=queue if queue is not None else BeadsQueue(repo_root=tmp_path),
        runtime_toml_path=runtime_toml,
        project_root=tmp_path,
        log=structlog.get_logger(),
        services=services,
        checks=checks,
    )
    if config is not None:
        sup.config = config
    return sup


def make_running_worker(
    task_id: str,
    tmp_path: Path | None = None,
    *,
    task: Task | None = None,
    run=None,
    future=None,
    attempt_n: int = 1,
) -> RunningWorker:
    """Build a RunningWorker for tests (fake run/future unless given)."""
    _ = tmp_path  # reserved: callers pass it for symmetry with make_supervisor
    return RunningWorker(
        task=task or Task(id=task_id, title="T", description=None, status="in_progress"),
        run=run if run is not None else MagicMock(),
        future=future if future is not None else MagicMock(),
        attempt_n=attempt_n,
        started_at=datetime.now(tz=UTC),
    )
