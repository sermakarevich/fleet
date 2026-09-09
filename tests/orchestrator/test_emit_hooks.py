"""Tests for orchestrator/service.py hooks: skip absent hooks, keep order."""

from __future__ import annotations

import asyncio

from fleet.orchestrator.service import ServiceOrder, build_hooks, emit, emit_hooks
from fleet.orchestrator.state import SupervisorState
from tests.conftest import make_supervisor


def _state(tmp_path) -> SupervisorState:  # type: ignore[no-untyped-def]
    return make_supervisor(tmp_path, services=[], checks=[]).state


class _Hookless:
    """A service with no hooks at all: only a name, an order, and a body."""

    name = "hookless"
    order = ServiceOrder.Config

    async def serve(self, st: SupervisorState) -> None:
        return None


class _Hooked:
    """A service recording the hooks it receives."""

    def __init__(self, name: str, order: ServiceOrder, calls: list) -> None:
        self.name = name
        self.order = order
        self._calls = calls

    async def serve(self, st: SupervisorState) -> None:
        return None

    async def on_start(self, st: SupervisorState) -> None:
        self._calls.append((self.name, "on_start"))

    async def on_stop(self, st: SupervisorState) -> None:
        self._calls.append((self.name, "on_stop"))


def test_service_without_a_hook_is_skipped(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """build_hooks skips services lacking the hook; emit never probes them."""
    st = _state(tmp_path)
    calls: list = []
    hooked = _Hooked("rec", ServiceOrder.Claim, calls)
    hooks = build_hooks([_Hookless(), hooked])
    assert [owner for owner, _ in hooks["on_start"]] == ["rec"]
    assert hooks["on_stop"] != []
    asyncio.run(emit_hooks(hooks, "on_start", st))
    assert calls == [("rec", "on_start")]


def test_hooks_run_in_service_order(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Collected hooks run sorted by order even when services are shuffled."""
    st = _state(tmp_path)
    calls: list = []
    late = _Hooked("late", ServiceOrder.Gc, calls)
    early = _Hooked("early", ServiceOrder.Config, calls)
    mid = _Hooked("mid", ServiceOrder.Claim, calls)
    asyncio.run(emit([late, mid, _Hookless(), early], "on_start", st))
    assert calls == [("early", "on_start"), ("mid", "on_start"), ("late", "on_start")]


def test_emit_unknown_event_is_noop(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Emitting an event nobody defines calls nothing and raises nothing."""
    st = _state(tmp_path)
    calls: list = []
    asyncio.run(emit([_Hookless(), _Hooked("rec", ServiceOrder.Config, calls)], "nope", st))
    assert calls == []
