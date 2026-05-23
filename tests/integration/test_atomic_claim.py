"""FR-04: Exactly one concurrent claim succeeds when two workers race."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from fleet.schemas import Task

from tests.integration.conftest import (
    MemoryQueue,
    beads_functional,
    init_beads_queue,
)

_BEADS_OK = beads_functional()


# ---------------------------------------------------------------------------
# Real-beads atomic claim (requires bd on PATH)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _BEADS_OK, reason="bd not functional in fresh git repo")
def test_atomic_claim_real_beads(tmp_path: Path) -> None:
    """With real beads, exactly one concurrent claim wins. (FR-04)"""
    q1 = init_beads_queue(tmp_path)
    from fleet.queue import BeadsQueue

    q2 = BeadsQueue(tmp_path)

    task = q1.create_task(title="atomic-claim-target")

    async def _run() -> tuple[Task | None, Task | None]:
        # Fire both claims concurrently in the same event loop
        results = await asyncio.gather(
            asyncio.get_event_loop().run_in_executor(None, q1.claim_next, "worker-1"),
            asyncio.get_event_loop().run_in_executor(None, q2.claim_next, "worker-2"),
        )
        return results  # type: ignore[return-value]

    r1, r2 = asyncio.run(_run())

    claimed = [r for r in (r1, r2) if r is not None]
    not_claimed = [r for r in (r1, r2) if r is None]

    assert len(claimed) == 1, f"exactly one claim should win; got {len(claimed)}"
    assert len(not_claimed) == 1, "the other claim should return None"
    assert claimed[0].id == task.id
    assert claimed[0].status == "in_progress"

    # Verify bd status
    current = q1.get(task.id)
    assert current.status == "in_progress"


# ---------------------------------------------------------------------------
# MemoryQueue stub claim (asyncio cooperative, no real atomicity)
# NOTE: MemoryQueue is single-threaded via asyncio; claim_next has no await so
#       no interleaving can occur.  This validates the stub's semantics.
# ---------------------------------------------------------------------------


def test_atomic_claim_memory_queue_stub(tmp_path: Path) -> None:
    """MemoryQueue stub: exactly one of two concurrent claim_next calls wins. (FR-04)"""
    # Two separate MemoryQueue instances sharing the same underlying task dict
    # is not how real beads works, so we test one queue with two concurrent callers.
    queue = MemoryQueue()
    task = Task(id="t-001", title="atomic-target", description=None, status="open")
    queue.add_task(task)

    results: list[Task | None] = []

    async def _run() -> None:
        # In asyncio, claim_next is synchronous (no await) so no real concurrent
        # interleaving, but we validate the expected stub semantics.
        r1 = await asyncio.get_event_loop().run_in_executor(None, queue.claim_next, "w1")
        r2 = await asyncio.get_event_loop().run_in_executor(None, queue.claim_next, "w2")
        results.extend([r1, r2])

    asyncio.run(_run())

    claimed = [r for r in results if r is not None]
    assert len(claimed) == 1, f"exactly one claim should succeed; got {len(claimed)}"
    assert claimed[0].id == "t-001"
    assert claimed[0].status == "in_progress"
    assert results.count(None) == 1


def test_atomic_claim_task_in_progress_exactly_once(tmp_path: Path) -> None:
    """After a concurrent race, beads/stub shows the task as in_progress exactly once."""
    queue = MemoryQueue()
    task = Task(id="t-001", title="target", description=None, status="open")
    queue.add_task(task)

    async def _claim_many(n: int) -> list[Task | None]:
        coros = [
            asyncio.get_event_loop().run_in_executor(None, queue.claim_next, f"w-{i}")
            for i in range(n)
        ]
        return list(await asyncio.gather(*coros))

    results = asyncio.run(_claim_many(5))

    claimed = [r for r in results if r is not None]
    assert len(claimed) == 1, "exactly one claim should win out of 5 concurrent callers"
    assert queue._tasks["t-001"].status == "in_progress"
    assert len(queue.claims) == 1
