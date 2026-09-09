"""Tests for orchestrator/service.py: emit ordering and periodic ticks."""

from __future__ import annotations

import asyncio

from fleet.orchestrator.service import PeriodicService, ServiceOrder, emit
from fleet.orchestrator.state import SupervisorState
from tests.conftest import make_supervisor
from tests.helpers.wait import await_until


class _StubLog:
    def __init__(self) -> None:
        self.warnings: list[tuple[str, dict]] = []

    def info(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        pass

    def warning(self, event: str, **kwargs) -> None:  # noqa: ANN003
        self.warnings.append((event, kwargs))


def _state(tmp_path, log=None):  # type: ignore[no-untyped-def]
    sup = make_supervisor(tmp_path, services=[], checks=[])
    if log is not None:
        sup.state.log = log
    return sup.state


class _Recorder:
    def __init__(self, name: str, order: ServiceOrder, calls: list, fail_on: str = "") -> None:
        self.name = name
        self.order = order
        self._calls = calls
        self._fail_on = fail_on

    async def on_start(self, st: SupervisorState) -> None:
        self._calls.append((self.name, "on_start"))
        if self._fail_on == "on_start":
            raise RuntimeError("boom")

    async def on_stop(self, st: SupervisorState) -> None:
        self._calls.append((self.name, "on_stop"))

    async def serve(self, st: SupervisorState) -> None:
        return None


def test_emit_calls_in_order_regardless_of_list_order(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """emit runs on_start sorted by order even when the list is shuffled."""
    st = _state(tmp_path)
    calls: list = []
    late = _Recorder("late", ServiceOrder.Gc, calls)
    early = _Recorder("early", ServiceOrder.Config, calls)
    mid = _Recorder("mid", ServiceOrder.Claim, calls)
    asyncio.run(emit([late, mid, early], "on_start", st))
    assert calls == [("early", "on_start"), ("mid", "on_start"), ("late", "on_start")]


def test_emit_continues_after_one_raises(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """emit still calls later services when one service raises."""
    log = _StubLog()
    st = _state(tmp_path, log=log)
    calls: list = []
    bad = _Recorder("bad", ServiceOrder.Config, calls, fail_on="on_start")
    good = _Recorder("good", ServiceOrder.Claim, calls)
    asyncio.run(emit([bad, good], "on_start", st))
    assert ("good", "on_start") in calls
    assert any(event == "bad_on_start_failed" for event, _ in log.warnings)


def _counter_service(interval_sec: float, ticks: list, fail_first: bool = False) -> PeriodicService:
    """A PeriodicService whose tick counts calls (and optionally fails once)."""
    state = {"fail_first": fail_first}

    async def tick(st: SupervisorState) -> None:
        ticks.append(1)
        if state["fail_first"]:
            state["fail_first"] = False
            raise RuntimeError("bad tick")

    return PeriodicService(
        name="counter", order=ServiceOrder.Claim, interval_sec=interval_sec, tick=tick
    )


def test_periodic_service_ticks_and_stops_on_shutdown(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """PeriodicService ticks repeatedly and exits once shutting_down is set."""
    st = _state(tmp_path)
    ticks: list = []
    svc = _counter_service(interval_sec=0.01, ticks=ticks)

    async def _run() -> None:
        task = asyncio.create_task(svc.serve(st))
        assert await await_until(lambda: len(ticks) >= 3), "service never ticked 3 times"
        st.shutting_down = True
        await asyncio.wait_for(task, timeout=2.0)

    asyncio.run(_run())
    assert len(ticks) >= 3


def test_periodic_tick_exception_is_logged_not_raised(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """A failing tick logs a warning and the loop keeps ticking."""
    log = _StubLog()
    st = _state(tmp_path, log=log)
    ticks: list = []
    svc = _counter_service(interval_sec=0.01, ticks=ticks, fail_first=True)

    async def _run() -> None:
        task = asyncio.create_task(svc.serve(st))
        assert await await_until(lambda: len(ticks) >= 2), "service never ticked twice"
        st.shutting_down = True
        await asyncio.wait_for(task, timeout=2.0)

    asyncio.run(_run())
    assert len(ticks) >= 2
    assert any(event == "counter_tick_failed" for event, _ in log.warnings)
