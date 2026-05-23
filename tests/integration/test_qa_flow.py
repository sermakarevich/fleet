"""FR-16 / FR-17 / FR-18: Agent-blocked Q&A flow with real beads."""
from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest

from tests.integration.conftest import (
    FakeClaudeCoder,
    beads_functional,
    fast_config,
    init_beads_queue,
    make_supervisor,
    run_until,
)


pytestmark = pytest.mark.skipif(not beads_functional(), reason="bd not functional in fresh git repo")


def test_qa_block_and_resume(tmp_path: Path) -> None:
    """Agent blocks task with Q&A, human answers, task completes. (FR-16/17)"""
    queue = init_beads_queue(tmp_path)
    task = queue.create_task(
        title="qa-flow-task",
        description="Integration test for Q&A flow",
    )
    task_id = task.id

    config = fast_config(claim_poll_interval_sec=1)

    # Run 1: block_via_bd — agent writes Q block and marks blocked via bd
    # Run 2: read_qa_and_close — agent reads A block and closes via bd
    coder = FakeClaudeCoder(
        scenarios=["block_via_bd", "read_qa_and_close"],
        FAKE_CLAUDE_BD_ROOT=str(tmp_path),
    )
    sup = make_supervisor(tmp_path, queue, coder=coder, config=config)

    # Phase 1: run until task is blocked
    blocked_event = asyncio.Event()

    async def _phase1() -> None:
        sup_task = asyncio.create_task(sup.run())
        try:
            # Wait until beads shows the task as blocked
            deadline = asyncio.get_event_loop().time() + 15.0
            while asyncio.get_event_loop().time() < deadline:
                await asyncio.sleep(0.5)
                try:
                    current = queue.get(task_id)
                    if current.status == "blocked":
                        blocked_event.set()
                        break
                except Exception:
                    pass
        finally:
            await sup._shutdown()
            try:
                await asyncio.wait_for(sup_task, timeout=5.0)
            except asyncio.TimeoutError:
                sup_task.cancel()
                try:
                    await sup_task
                except (asyncio.CancelledError, Exception):
                    pass

    asyncio.run(_phase1())

    assert blocked_event.is_set(), "task should be blocked after block_via_bd scenario"

    # Verify Q&A.md has the Q block
    task_dir = tmp_path / "tasks" / task_id
    qa_path = task_dir / "artifacts" / "Q&A.md"
    assert qa_path.exists(), "Q&A.md should exist after block_via_bd"
    qa_content = qa_path.read_text()
    assert "## Q:" in qa_content

    # Phase 2: human answers — append A block and flip status to open
    with qa_path.open("a") as fh:
        fh.write("## A: 42\n\nThe magic number is 42.\n\n")

    subprocess.run(
        ["bd", "update", task_id, "--status", "open"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    # Phase 3: run supervisor again until task is closed
    closed_event = asyncio.Event()

    async def _phase3() -> None:
        sup_task = asyncio.create_task(sup.run())
        try:
            deadline = asyncio.get_event_loop().time() + 15.0
            while asyncio.get_event_loop().time() < deadline:
                await asyncio.sleep(0.5)
                try:
                    current = queue.get(task_id)
                    if current.status == "closed":
                        closed_event.set()
                        break
                except Exception:
                    pass
        finally:
            await sup._shutdown()
            try:
                await asyncio.wait_for(sup_task, timeout=5.0)
            except asyncio.TimeoutError:
                sup_task.cancel()
                try:
                    await sup_task
                except (asyncio.CancelledError, Exception):
                    pass

    # Need a fresh supervisor (can't reuse after shutdown)
    sup2 = make_supervisor(tmp_path, queue, coder=coder, config=config)

    async def _phase3_with_sup2() -> None:
        sup_task = asyncio.create_task(sup2.run())
        try:
            deadline = asyncio.get_event_loop().time() + 15.0
            while asyncio.get_event_loop().time() < deadline:
                await asyncio.sleep(0.5)
                try:
                    current = queue.get(task_id)
                    if current.status == "closed":
                        closed_event.set()
                        break
                except Exception:
                    pass
        finally:
            await sup2._shutdown()
            try:
                await asyncio.wait_for(sup_task, timeout=5.0)
            except asyncio.TimeoutError:
                sup_task.cancel()
                try:
                    await sup_task
                except (asyncio.CancelledError, Exception):
                    pass

    asyncio.run(_phase3_with_sup2())

    assert closed_event.is_set(), "task should be closed after read_qa_and_close scenario"

    # events.jsonl should have records from both runs (append-only across runs)
    import json
    events_path = task_dir / "events.jsonl"
    assert events_path.exists()
    lines = [json.loads(l) for l in events_path.read_text().splitlines() if l.strip()]
    assert len(lines) >= 2, (
        f"events from both runs should be appended; got {len(lines)} records"
    )


def test_qa_blocked_no_failure_count(tmp_path: Path) -> None:
    """BLOCKED_BY_AGENT does not increment failure_count. (FR-16)"""
    from fleet.failures import failure_count

    queue = init_beads_queue(tmp_path)
    task = queue.create_task(title="qa-no-failure-task")
    task_id = task.id

    coder = FakeClaudeCoder(
        scenario="block_via_bd",
        FAKE_CLAUDE_BD_ROOT=str(tmp_path),
    )
    config = fast_config(claim_poll_interval_sec=1)
    sup = make_supervisor(tmp_path, queue, coder=coder, config=config)

    done = asyncio.Event()

    async def _run() -> None:
        sup_task = asyncio.create_task(sup.run())
        try:
            deadline = asyncio.get_event_loop().time() + 15.0
            while asyncio.get_event_loop().time() < deadline:
                await asyncio.sleep(0.5)
                try:
                    current = queue.get(task_id)
                    if current.status == "blocked":
                        done.set()
                        break
                except Exception:
                    pass
        finally:
            await sup._shutdown()
            try:
                await asyncio.wait_for(sup_task, timeout=5.0)
            except asyncio.TimeoutError:
                sup_task.cancel()
                try:
                    await sup_task
                except (asyncio.CancelledError, Exception):
                    pass

    asyncio.run(_run())

    assert done.is_set()
    task_dir = tmp_path / "tasks" / task_id
    assert failure_count(task_dir) == 0, (
        "BLOCKED_BY_AGENT must not burn retries"
    )
