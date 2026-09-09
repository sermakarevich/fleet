"""Tests for orchestrator/config_reload.py: tick swaps config and emits the event."""

from __future__ import annotations

import asyncio
from pathlib import Path

from fleet.core.config import RuntimeConfig
from fleet.core.limits import CONFIG_POLL_INTERVAL_SEC
from fleet.orchestrator.config_reload import make_config_reload
from fleet.orchestrator.service import PeriodicService, ServiceOrder
from fleet.orchestrator.state import SupervisorState
from fleet.state.config_file import write as write_atomic
from tests.conftest import make_supervisor


class _Recorder:
    """Record on_config_reloaded calls with old/new configs."""

    name = "recorder"
    order = ServiceOrder.Claim

    def __init__(self) -> None:
        self.calls: list = []

    async def serve(self, st: SupervisorState) -> None:
        return None

    async def on_config_reloaded(
        self, st: SupervisorState, old: RuntimeConfig, new: RuntimeConfig
    ) -> None:
        self.calls.append((old, new))


def _state_with(tmp_path: Path, reloader: PeriodicService, recorder: _Recorder) -> SupervisorState:
    sup = make_supervisor(tmp_path, services=[], checks=[])
    st = sup.state
    st.services = [reloader, recorder]
    return st


def test_tick_swaps_config_and_fires_event(tmp_path: Path) -> None:
    """A changed runtime.toml swaps st.config and fires on_config_reloaded."""
    toml_path = tmp_path / "runtime.toml"
    write_atomic(toml_path, {"max_concurrent": "3"})
    reloader = make_config_reload(interval_sec=0.01)
    recorder = _Recorder()
    st = _state_with(tmp_path, reloader, recorder)
    st.config = RuntimeConfig(max_concurrent=3)

    async def _run() -> None:
        write_atomic(toml_path, {"max_concurrent": "7"})
        await reloader.tick(st)

    asyncio.run(_run())
    assert st.config.max_concurrent == 7
    assert len(recorder.calls) == 1
    old, new = recorder.calls[0]
    assert old.max_concurrent == 3
    assert new.max_concurrent == 7


def test_tick_no_change_fires_no_event(tmp_path: Path) -> None:
    """A second tick without a file change emits nothing."""
    reloader = make_config_reload(interval_sec=0.01)
    recorder = _Recorder()
    st = _state_with(tmp_path, reloader, recorder)

    async def _run() -> None:
        await reloader.tick(st)  # first tick loads (mtime was None)
        recorder.calls.clear()
        await reloader.tick(st)  # nothing changed

    asyncio.run(_run())
    assert recorder.calls == []


def test_default_interval_matches_limits() -> None:
    """Default interval comes from core/limits.py; factory arg overrides it."""
    assert make_config_reload().interval_sec == CONFIG_POLL_INTERVAL_SEC
    assert make_config_reload(interval_sec=0.01).interval_sec == 0.01
