"""End-to-end: a task created with cwd=<project> runs the subprocess in that dir.

Verifies the centralized-fleet model: fleet_home holds the queue, but each task
carries its own working directory which the supervisor honors.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from tests.integration.conftest import (
    BD_AVAILABLE,
    FakeClaudeCoder,
    beads_functional,
    fast_config,
    init_beads_queue,
    make_supervisor,
    run_until,
)

pytestmark = pytest.mark.skipif(
    not BD_AVAILABLE or not beads_functional(),
    reason="bd not installed or not functional in this environment",
)


def test_task_runs_in_its_own_cwd(tmp_path: Path) -> None:
    fleet_home = tmp_path / "fleet-home"
    fleet_home.mkdir()
    project_dir = tmp_path / "projectA"
    project_dir.mkdir()
    cwd_file = tmp_path / "recorded_cwd.txt"

    queue = init_beads_queue(fleet_home)
    task = queue.create_task("Test task", cwd=str(project_dir))
    assert task.cwd == str(project_dir)

    done = asyncio.Event()
    coder = FakeClaudeCoder(
        scenario="record_cwd",
        FAKE_CLAUDE_CWD_FILE=str(cwd_file),
    )
    supervisor = make_supervisor(
        fleet_home,
        queue,
        coder=coder,
        config=fast_config(),
    )

    # Stop as soon as the task completes successfully.
    from fleet.orchestrator.service import Service, ServiceOrder

    class _DoneRecorder(Service):
        order = ServiceOrder.Logging
        name = "test_done_recorder"

        async def on_worker_finished(self, st, worker, outcome) -> None:  # type: ignore[no-untyped-def]
            done.set()

    supervisor.state.services.append(_DoneRecorder())

    asyncio.run(run_until(supervisor, done, timeout=20.0))

    assert cwd_file.exists(), "fake_claude did not run"
    recorded = cwd_file.read_text().strip()
    assert Path(recorded).resolve() == project_dir.resolve(), (
        f"subprocess ran in {recorded}, expected {project_dir}"
    )

    # Centralized layout: task state lives under FLEET_HOME, not the task cwd.
    task_dir = fleet_home / "tasks" / task.id
    assert task_dir.exists(), (
        f"task dir not centralized in fleet_home: expected {task_dir}"
    )
    assert (task_dir / "STATE.md").exists()
    assert (task_dir / "task.json").exists()
