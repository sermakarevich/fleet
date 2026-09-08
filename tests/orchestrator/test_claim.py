"""Tests for orchestrator/claim.py: pure helpers and the Claim service tick."""

from __future__ import annotations

import asyncio
import types
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fleet.core.limits import CLAIM_POLL_INTERVAL_SEC
from fleet.core.task import Task
from fleet.orchestrator import claim as claim_mod
from fleet.orchestrator.claim import (
    Claim,
    cap_for_coder,
    parse_overrides,
    running_by_coder,
)
from fleet.orchestrator.service import ServiceOrder
from tests.conftest import make_running_worker, make_supervisor


def test_parse_overrides_empty() -> None:
    assert parse_overrides("") == {}


def test_parse_overrides_single() -> None:
    assert parse_overrides("claude:2") == {"claude": 2}


def test_parse_overrides_multiple_with_whitespace() -> None:
    assert parse_overrides("claude:2, opencode:4 , pi:1") == {
        "claude": 2,
        "opencode": 4,
        "pi": 1,
    }


def test_parse_overrides_malformed_entries() -> None:
    assert parse_overrides("claude,opencode:x,:3,foo:0,bar:-1") == {}


def test_cap_for_coder_with_override() -> None:
    assert cap_for_coder("claude", 3, "claude:2") == 2


def test_cap_for_coder_fallback() -> None:
    assert cap_for_coder("pi", 3, "claude:2") == 3


def test_running_by_coder_empty() -> None:
    assert running_by_coder([], "claude") == {}


def test_running_by_coder_counts_by_effective_coder() -> None:
    tasks = [
        types.SimpleNamespace(coder="claude"),
        types.SimpleNamespace(coder=None),
        types.SimpleNamespace(coder="opencode"),
        types.SimpleNamespace(coder=None),
        types.SimpleNamespace(coder="claude"),
    ]
    result = running_by_coder(tasks, "default_coder")
    assert result == {"claude": 2, "opencode": 1, "default_coder": 2}


def test_claim_order_and_default_interval() -> None:
    assert Claim.order == ServiceOrder.Claim
    assert Claim().interval_sec == CLAIM_POLL_INTERVAL_SEC
    assert Claim(interval_sec=0.01).interval_sec == 0.01


# ---------------------------------------------------------------------------
# Claim.tick
# ---------------------------------------------------------------------------


class StubQueue:
    """Queue double that honours can_claim like the real BeadsQueue."""

    def __init__(self, task: Task | None = None) -> None:
        self._task = task
        self.claims = 0
        self.released: list[tuple[str, str]] = []

    def claim_next(self, claimer_id, *, can_claim=None):
        self.claims += 1
        if self._task is None:
            return None
        if can_claim is not None and not can_claim(self._task.coder):
            return None
        task, self._task = self._task, None
        return task

    def release(self, task_id, reason="", wait_sec=0):
        self.released.append((task_id, reason))


def _task(task_id: str = "t-001") -> Task:
    return Task(id=task_id, title="Test", description=None, status="open")


def test_tick_paused_skips_claim(tmp_path: Path) -> None:
    queue = StubQueue(_task())
    sup = make_supervisor(tmp_path, queue=queue, services=[], checks=[])
    sup.state.paused_until = datetime.now(tz=UTC) + timedelta(seconds=300)
    asyncio.run(Claim(interval_sec=0.01).tick(sup.state))
    assert queue.claims == 0
    assert sup.state.running == {}


def test_tick_clears_expired_pause_and_claims(tmp_path: Path) -> None:
    queue = StubQueue(None)
    sup = make_supervisor(tmp_path, queue=queue, services=[], checks=[])
    sup.state.paused_until = datetime.now(tz=UTC) - timedelta(seconds=1)
    asyncio.run(Claim(interval_sec=0.01).tick(sup.state))
    assert sup.state.paused_until is None
    assert queue.claims == 1


def test_tick_pause_file_skips_claim(tmp_path: Path) -> None:
    queue = StubQueue(_task())
    sup = make_supervisor(tmp_path, queue=queue, services=[], checks=[])
    (tmp_path / ".pause").write_text("1")
    asyncio.run(Claim(interval_sec=0.01).tick(sup.state))
    assert queue.claims == 0
    assert sup.state.running == {}


def test_tick_cap_reached_claims_nothing(tmp_path: Path, monkeypatch) -> None:
    queue = StubQueue(_task("t-new"))
    sup = make_supervisor(tmp_path, queue=queue, services=[], checks=[])
    for i in range(3):
        sup.state.running[f"t-{i:03d}"] = make_running_worker(f"t-{i:03d}", tmp_path)
    spawned: list[str] = []
    monkeypatch.setattr(claim_mod, "spawn_worker", lambda st, t: spawned.append(t.id))
    asyncio.run(Claim(interval_sec=0.01).tick(sup.state))
    assert spawned == []
    assert "t-new" not in sup.state.running


def test_tick_spawn_failure_releases(tmp_path: Path, monkeypatch) -> None:
    queue = StubQueue(_task("t-boom"))
    sup = make_supervisor(tmp_path, queue=queue, services=[], checks=[])

    def _boom(st, t):
        raise AttributeError("half-edited coder code")

    monkeypatch.setattr(claim_mod, "spawn_worker", _boom)
    asyncio.run(Claim(interval_sec=0.01).tick(sup.state))
    assert queue.released and queue.released[0][0] == "t-boom"
    assert "spawn failed" in queue.released[0][1]
    assert "t-boom" not in sup.state.running


def test_tick_skips_task_already_running(tmp_path: Path, monkeypatch) -> None:
    queue = StubQueue(_task("t-dup"))
    sup = make_supervisor(tmp_path, queue=queue, services=[], checks=[])
    sup.state.running["t-dup"] = make_running_worker("t-dup", tmp_path)
    spawned: list[str] = []
    monkeypatch.setattr(claim_mod, "spawn_worker", lambda st, t: spawned.append(t.id))
    asyncio.run(Claim(interval_sec=0.01).tick(sup.state))
    assert spawned == []
    assert len(sup.state.running) == 1


def test_tick_terminal_spawn_registers_nothing(tmp_path: Path, monkeypatch) -> None:
    queue = StubQueue(_task("t-term"))
    sup = make_supervisor(tmp_path, queue=queue, services=[], checks=[])
    monkeypatch.setattr(claim_mod, "spawn_worker", lambda st, t: None)
    asyncio.run(Claim(interval_sec=0.01).tick(sup.state))
    assert "t-term" not in sup.state.running
    assert queue.released == []


def test_tick_happy_path_registers_and_emits(tmp_path: Path, monkeypatch) -> None:
    queue = StubQueue(_task("t-new"))
    sup = make_supervisor(tmp_path, queue=queue, services=[], checks=[])
    worker = make_running_worker("t-new", tmp_path)
    monkeypatch.setattr(claim_mod, "spawn_worker", lambda st, t: worker)
    started: list[str] = []

    async def _on_started(st, w) -> None:
        started.append(w.task.id)

    recorder = types.SimpleNamespace(
        order=ServiceOrder.Triage, name="rec", on_worker_started=_on_started
    )
    sup.state.services = [recorder]
    asyncio.run(Claim(interval_sec=0.01).tick(sup.state))
    assert sup.state.running["t-new"] is worker
    assert started == ["t-new"]
