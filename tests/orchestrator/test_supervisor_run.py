"""Tests for the thin Supervisor.run() lifecycle runner."""

from __future__ import annotations

import asyncio

from fleet.orchestrator.service import Service, ServiceOrder
from fleet.orchestrator.state import SupervisorState
from tests.conftest import make_supervisor


class _HookRecorder(Service):
    def __init__(self, name: str, order: ServiceOrder, calls: list) -> None:
        self.name = name
        self.order = order
        self._calls = calls

    async def on_start(self, st: SupervisorState) -> None:
        self._calls.append((self.name, "on_start"))

    async def on_stop(self, st: SupervisorState) -> None:
        self._calls.append((self.name, "on_stop"))


def test_run_emits_start_in_order_then_stop_after_shutdown(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """run() fires on_start in order, serves, then on_stop after _shutdown."""
    calls: list = []
    first = _HookRecorder("first", ServiceOrder.Config, calls)
    second = _HookRecorder("second", ServiceOrder.Gc, calls)
    sup = make_supervisor(tmp_path, services=[second, first], checks=[])

    async def _run() -> int:
        run_task = asyncio.create_task(sup.run())
        while len(calls) < 2:
            await asyncio.sleep(0.005)
        await sup._shutdown()
        return await asyncio.wait_for(run_task, timeout=5.0)

    rc = asyncio.run(_run())
    assert rc == 0
    assert calls == [
        ("first", "on_start"),
        ("second", "on_start"),
        ("first", "on_stop"),
        ("second", "on_stop"),
    ]


def test_run_returns_zero_with_no_services(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """run() with no services still shuts down cleanly and returns 0."""
    sup = make_supervisor(tmp_path, services=[], checks=[])

    async def _run() -> int:
        run_task = asyncio.create_task(sup.run())
        await asyncio.sleep(0.02)
        await sup._shutdown()
        return await asyncio.wait_for(run_task, timeout=5.0)

    assert asyncio.run(_run()) == 0


def test_default_services_cover_all_concerns(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """default_services() wires one service per concern, in non-decreasing order."""
    from fleet.orchestrator import default_services

    services = default_services()
    names = sorted(svc.name for svc in services)
    assert names == sorted(
        [
            "config_reload",
            "lease_reconcile",
            "claim",
            "merge_validation",
            "reap",
            "stall_watch",
            "kill_sentinel",
            "triage",
            "retention_gc",
            "status_log",
        ]
    )
    orders = [svc.order for svc in services]
    assert orders == sorted(orders)
