"""Tests for orchestrator/kill_sentinel.py: .kill files trigger runner.kill()."""

from __future__ import annotations

import asyncio
from pathlib import Path

from fleet.orchestrator.kill_sentinel import KillSentinel
from fleet.state.paths import task_dir
from tests.conftest import make_running_worker, make_supervisor


class _FakeRun:
    """Stand-in for WorkerRun counting kill() calls."""

    def __init__(self) -> None:
        self.kill_calls = 0

    async def kill(self, reason: str = "manual_kill") -> None:
        self.kill_calls += 1


def test_tick_deletes_kill_file_and_kills_once(tmp_path: Path) -> None:
    """A present .kill file is unlinked and run.kill() is called exactly once."""
    sup = make_supervisor(tmp_path, services=[], checks=[])
    st = sup.state
    fake = _FakeRun()
    st.running["t-kill"] = make_running_worker("t-kill", tmp_path, run=fake)
    kill_file = task_dir(tmp_path, "t-kill") / ".kill"
    kill_file.parent.mkdir(parents=True, exist_ok=True)
    kill_file.touch()

    asyncio.run(KillSentinel().tick(st))

    assert not kill_file.exists()
    assert fake.kill_calls == 1


def test_tick_without_kill_file_kills_nothing(tmp_path: Path) -> None:
    """No .kill file means no kill() call."""
    sup = make_supervisor(tmp_path, services=[], checks=[])
    st = sup.state
    fake = _FakeRun()
    st.running["t-idle"] = make_running_worker("t-idle", tmp_path, run=fake)
    task_dir(tmp_path, "t-idle").mkdir(parents=True, exist_ok=True)

    asyncio.run(KillSentinel().tick(st))

    assert fake.kill_calls == 0


def test_default_interval_is_one_second() -> None:
    """Default cadence is 1.0s; ctor arg overrides it."""
    assert KillSentinel().interval_sec == 1.0
    assert KillSentinel(interval_sec=0.01).interval_sec == 0.01
