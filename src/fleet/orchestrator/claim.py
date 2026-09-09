"""Claim service: poll the queue, enforce per-coder caps, spawn workers.

One periodic service with one job — turn a claimable bead into a running
worker. Merge validation used to ride along at the end of this loop; it is
now the separate `merge_validation` module.
"""

from __future__ import annotations

import asyncio
from functools import partial
from typing import TYPE_CHECKING

from fleet.core.limits import CLAIM_POLL_INTERVAL_SEC
from fleet.orchestrator.service import ServiceOrder, emit, run_periodic
from fleet.orchestrator.spawn import spawn_worker

if TYPE_CHECKING:
    from fleet.core.task import Task
    from fleet.orchestrator.state import SupervisorState


def parse_overrides(raw: str) -> dict[str, int]:
    """Parse "claude:2,opencode:4" into {"claude": 2, "opencode": 4}.

    Blank or malformed entries and non-positive counts are ignored.
    """
    result: dict[str, int] = {}
    for raw_part in raw.split(","):
        part = raw_part.strip()
        if not part or ":" not in part:
            continue
        name, _, value = part.partition(":")
        name = name.strip()
        try:
            count = int(value.strip())
        except ValueError:
            continue
        if name and count > 0:
            result[name] = count
    return result


def cap_for_coder(coder: str, max_concurrent: int, overrides: str) -> int:
    """Concurrency cap for `coder`: its override if listed, else `max_concurrent`."""
    return parse_overrides(overrides).get(coder, max_concurrent)


def running_by_coder(tasks, default_coder: str) -> dict[str, int]:
    """Count how many of `tasks` run under each coder.

    `tasks` is any iterable of objects with a `.coder` attribute (None means
    the task uses the default coder).
    """
    counts: dict[str, int] = {}
    for task in tasks:
        coder = getattr(task, "coder", None) or default_coder
        counts[coder] = counts.get(coder, 0) + 1
    return counts


def can_claim(st: SupervisorState, coder: str | None) -> bool:
    """True when another worker under `coder` fits below its cap."""
    running = running_by_coder((rw.task for rw in st.running.values()), st.config.coder)
    effective = coder or st.config.coder
    cap = cap_for_coder(effective, st.config.max_concurrent, st.config.max_concurrent_overrides)
    return running.get(effective, 0) < cap


async def release_after_spawn_failure(st: SupervisorState, task: Task, exc: Exception) -> None:
    """Hand the bead back after an unexpected spawn error; never raises."""
    st.log.exception("spawn_failed", task_id=task.id, error=str(exc))
    try:
        await asyncio.to_thread(
            st.queue.release, task.id, reason=f"spawn failed: {exc}", wait_sec=60
        )
    except Exception:  # noqa: BLE001 - the loop must survive a broken queue
        st.log.exception("spawn_failed_release", task_id=task.id)


class Claim:
    """Poll the queue and spawn one worker per tick when a cap allows."""

    order = ServiceOrder.Claim
    name = "claim"

    def __init__(self, interval_sec: float | None = None) -> None:
        self.interval_sec = interval_sec if interval_sec is not None else CLAIM_POLL_INTERVAL_SEC

    def _paused(self, st: SupervisorState) -> bool:
        """True while the rate-limit pause holds; clears it once it passes.

        Claim is the only service that clears `paused_until` (Reap sets it).
        """
        if st.paused_until is None:
            return False
        if st.clock.now() < st.paused_until:
            return True
        st.paused_until = None
        return False

    async def tick(self, st: SupervisorState) -> None:
        """Claim one bead and spawn its worker, or do nothing this tick."""
        if self._paused(st):
            return
        if (st.fleet_home / ".pause").exists():
            return
        # bd is a subprocess; run it in a worker thread
        # so the event loop keeps tailing runner output.
        task = await asyncio.to_thread(
            st.queue.claim_next, "supervisor", can_claim=partial(can_claim, st)
        )
        if task is None:
            return
        if task.id in st.running:
            st.log.warning("task_already_in_flight", task_id=task.id, in_flight=len(st.running))
            return
        st.log.info(
            "task_claimed",
            task_id=task.id,
            title=task.title[:80],
            in_flight=len(st.running) + 1,
            cap=st.config.max_concurrent,
            usage_pct=st.rate_gauge.current_pct(),
        )
        try:
            worker = spawn_worker(st, task)
        except Exception as exc:  # noqa: BLE001 - a spawn bug must not kill the loop
            await release_after_spawn_failure(st, task, exc)
            return
        if worker is None:
            return
        st.running[task.id] = worker
        await emit(st.services, "on_worker_started", st, worker)

    async def serve(self, st: SupervisorState) -> None:
        """Tick on the claim cadence until shutdown (shared periodic loop)."""
        await run_periodic(self.name, self.interval_sec, self.tick, st)
