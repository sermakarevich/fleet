"""Tests for workers/observe.py. Mirrors the source path."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import structlog

from fleet.core.config import RuntimeConfig
from fleet.core.job_ready import BeadSummary
from fleet.core.task import Task, TaskOutcome, TaskOutcomeRecord
from fleet.orchestrator.supervisor import Supervisor
from fleet.state import attempts
from fleet.state.paths import task_dir as _task_dir
from fleet.workers.base import StepContext
from fleet.workers.observe import (
    CHILDREN_MD_MAX_BYTES,
    CollectChildren,
    Observer,
    SpawnFollowups,
    WaitChildren,
    plan_observer,
)


class FakeQueue:
    """Queue double: canned children, recorded creates/comments."""

    def __init__(self, children: list | None = None) -> None:
        self._children = children or []
        self.created: list[tuple[str, dict]] = []
        self.comments: list[tuple[str, str]] = []

    def list_children(self, epic_id: str):
        return self._children

    def create_child(self, epic_id: str, spec: dict):
        child_id = f"kid-{len(self.created) + 1}"
        self.created.append((epic_id, spec))
        return SimpleNamespace(id=child_id)

    def comment(self, task_id: str, body: str) -> None:
        self.comments.append((task_id, body))


def _ctx(
    tmp_path: Path,
    task_id: str = "epic-1",
    queue: FakeQueue | None = None,
) -> tuple[StepContext, FakeQueue]:
    queue = queue if queue is not None else FakeQueue()
    task_dir = _task_dir(tmp_path, task_id)
    task_dir.mkdir(parents=True, exist_ok=True)
    ctx = StepContext(
        task=Task(id=task_id, title="epic", description="goal", status="in_progress", type="epic"),
        task_dir=task_dir,
        project_root=tmp_path,
        fleet_home=tmp_path,
        coder=None,
        config=RuntimeConfig(),
        rate_gauge=None,  # type: ignore[arg-type]
        log=structlog.get_logger(),
    )
    return ctx, queue


def _factory(queue: FakeQueue):
    return lambda home: queue


def _write_child(
    tmp_path: Path,
    child_id: str,
    *,
    result: dict | None = None,
    touch_files: list[str] | None = None,
    blocked_reason: str | None = None,
) -> None:
    child_dir = _task_dir(tmp_path, child_id)
    child_dir.mkdir(parents=True, exist_ok=True)
    if result is not None:
        (child_dir / "RESULT.json").write_text(json.dumps(result))
    n = attempts.record_start(child_dir, coder="c", model="m", worker="task.fresh")
    attempts.record_end(
        child_dir, outcome="success", exit_code=0, reason="", action="close", n=n
    )
    adir = attempts.attempt_dir(child_dir, n)
    adir.mkdir(parents=True, exist_ok=True)
    (adir / "run.json").write_text(
        json.dumps({"launch": {"mode": "fresh", "pack_bytes": 0, "kind": "work"}})
    )
    events = [
        {
            "ts": "2026-01-01T00:00:00Z",
            "kind": "tool_use",
            "tool_name": "Read",
            "raw": {"input": {"file_path": p}},
        }
        for p in (touch_files or [])
    ]
    with (adir / "events.jsonl").open("w", encoding="utf-8") as f:
        for row in events:
            f.write(json.dumps(row) + "\n")
    meta: dict = {"id": child_id}
    if blocked_reason:
        meta["blocked_reason"] = blocked_reason
    (child_dir / "task.json").write_text(json.dumps(meta))


# ---------------------------------------------------------------------------
# WaitChildren
# ---------------------------------------------------------------------------


def test_wait_children_ok_when_all_terminal(tmp_path: Path) -> None:
    queue = FakeQueue([BeadSummary("c-1", "closed"), BeadSummary("c-2", "blocked")])
    ctx, _ = _ctx(tmp_path, queue=queue)
    result = asyncio.run(WaitChildren(_factory(queue)).run(ctx))
    assert result.status == "ok"
    assert ctx.scratch["children"] == [
        {"id": "c-1", "status": "closed"},
        {"id": "c-2", "status": "blocked"},
    ]


def test_wait_children_returns_waiting_while_running(tmp_path: Path) -> None:
    queue = FakeQueue([BeadSummary("c-1", "closed"), BeadSummary("c-2", "open")])
    ctx, _ = _ctx(tmp_path, queue=queue)
    result = asyncio.run(WaitChildren(_factory(queue)).run(ctx))
    assert result.status == "outcome"
    assert result.outcome is not None
    assert result.outcome.outcome == TaskOutcome.WAITING
    assert result.outcome.reason == "1 of 2 children still running"


def test_wait_children_leaves_live_result_alone(tmp_path: Path) -> None:
    """No rotation: reap snapshots the live RESULT.json and unlinks it."""
    queue = FakeQueue([BeadSummary("c-1", "closed")])
    ctx, _ = _ctx(tmp_path, queue=queue)
    (ctx.task_dir / "RESULT.json").write_text('{"schema": 1, "status": "done"}')
    result = asyncio.run(WaitChildren(_factory(queue)).run(ctx))
    assert result.status == "ok"
    assert (ctx.task_dir / "RESULT.json").exists()


# ---------------------------------------------------------------------------
# CollectChildren
# ---------------------------------------------------------------------------


def test_collect_children_writes_bounded_digest(tmp_path: Path) -> None:
    _write_child(
        tmp_path,
        "c-1",
        result={"schema": 1, "status": "done", "summary": "shipped feature"},
        touch_files=["/a.py"],
    )
    _write_child(
        tmp_path,
        "c-2",
        result={"schema": 1, "status": "blocked", "summary": "stuck"},
        blocked_reason="needs creds",
    )
    queue = FakeQueue([BeadSummary("c-1", "closed"), BeadSummary("c-2", "blocked")])
    ctx, _ = _ctx(tmp_path, queue=queue)
    ctx.attempt_dir = attempts.attempt_dir(ctx.task_dir, 1)
    ctx.attempt_n = 1
    result = asyncio.run(CollectChildren(_factory(queue)).run(ctx))
    assert result.status == "ok"
    body = (ctx.task_dir / "artifacts" / "CHILDREN.md").read_text(encoding="utf-8")
    assert len(body.encode("utf-8")) <= CHILDREN_MD_MAX_BYTES
    assert "c-1" in body and "shipped feature" in body and "files touched: 1" in body
    assert "needs creds" in body
    assert ctx.scratch["child_ids"] == ["c-1", "c-2"]
    assert ctx.scratch["blocked_children"] == 1
    assert ctx.scratch["launch_plan"].mode == "validate"
    run = json.loads((ctx.attempt_dir / "run.json").read_text(encoding="utf-8"))
    assert run["launch"]["mode"] == "validate"


def test_collect_children_truncates_oldest_first(tmp_path: Path) -> None:
    for i in range(30):
        _write_child(
            tmp_path,
            f"c-{i}",
            result={"schema": 1, "status": "done", "summary": "x" * 500},
        )
    children = [BeadSummary(f"c-{i}", "closed") for i in range(30)]
    queue = FakeQueue(children)
    ctx, _ = _ctx(tmp_path, queue=queue)
    result = asyncio.run(CollectChildren(_factory(queue)).run(ctx))
    assert result.status == "ok"
    body = (ctx.task_dir / "artifacts" / "CHILDREN.md").read_text(encoding="utf-8")
    assert len(body.encode("utf-8")) <= CHILDREN_MD_MAX_BYTES
    # Oldest dropped first: the newest child survives.
    assert "c-29" in body


# ---------------------------------------------------------------------------
# SpawnFollowups
# ---------------------------------------------------------------------------


def _write_partial_result(ctx: StepContext, followups: list) -> None:
    (ctx.task_dir / "RESULT.json").write_text(
        json.dumps({"schema": 1, "status": "partial", "summary": "more work", "followups": followups})
    )


def test_spawn_followups_creates_children_with_deps(tmp_path: Path) -> None:
    queue = FakeQueue()
    ctx, _ = _ctx(tmp_path, queue=queue)
    _write_partial_result(
        ctx,
        [
            {"title": "a", "body": "do a", "cwd": None, "depends_on": []},
            {"title": "b", "body": "do b", "cwd": None, "depends_on": ["a"]},
        ],
    )
    result = asyncio.run(SpawnFollowups(_factory(queue)).run(ctx))
    assert result.status == "ok"
    assert [spec["title"] for _, spec in queue.created] == ["a", "b"]
    assert queue.created[0][1]["depends_on"] == []
    assert queue.created[1][1]["depends_on"] == ["kid-1"]
    assert queue.created[0][0] == "epic-1"
    assert queue.comments == [("epic-1", "[fleet] opened 2 follow-ups: kid-1, kid-2")]


def test_spawn_followups_noop_without_followups(tmp_path: Path) -> None:
    queue = FakeQueue()
    ctx, _ = _ctx(tmp_path, queue=queue)
    result = asyncio.run(SpawnFollowups(_factory(queue)).run(ctx))
    assert result.status == "ok"
    assert queue.created == []
    assert queue.comments == []


def test_spawn_followups_invalid_list_commented_not_created(tmp_path: Path) -> None:
    queue = FakeQueue()
    ctx, _ = _ctx(tmp_path, queue=queue)
    _write_partial_result(ctx, [{"title": "a", "depends_on": ["ghost"]}])
    result = asyncio.run(SpawnFollowups(_factory(queue)).run(ctx))
    assert result.status == "ok"
    assert queue.created == []
    assert len(queue.comments) == 1
    assert "invalid follow-ups" in queue.comments[0][1]


# ---------------------------------------------------------------------------
# Blocked child -> RESULT blocked -> BLOCK (reap folds the declaration)
# ---------------------------------------------------------------------------


def test_blocked_child_digest_feeds_blocked_result(tmp_path: Path) -> None:
    _write_child(
        tmp_path,
        "c-1",
        result={"schema": 1, "status": "blocked", "summary": "stuck", "blocked_reason": "needs creds"},
        blocked_reason="needs creds",
    )
    queue = FakeQueue([BeadSummary("c-1", "blocked")])
    ctx, _ = _ctx(tmp_path, queue=queue)
    assert asyncio.run(CollectChildren(_factory(queue)).run(ctx)).status == "ok"
    body = (ctx.task_dir / "artifacts" / "CHILDREN.md").read_text(encoding="utf-8")
    assert "needs creds" in body

    # The validator then declares blocked; reap must BLOCK the epic.
    (ctx.task_dir / "RESULT.json").write_text(
        json.dumps(
            {"schema": 1, "status": "blocked", "summary": "stuck", "blocked_reason": "needs creds"}
        )
    )

    class StubQueue:
        def __init__(self) -> None:
            self.blocked: list[tuple[str, str]] = []

        def get(self, task_id: str):
            return Task(id=task_id, title="epic", description=None, status="in_progress", type="epic")

        def set_blocked(self, task_id: str, reason: str) -> None:
            self.blocked.append((task_id, reason))

        def comment(self, task_id: str, body: str) -> None:
            pass

    class StubCoder:
        name = "stub"

        def build_argv(self, task, task_dir, plan=None):
            return ["echo"]

        def env(self, task, task_dir):
            return {}

        def normalize_event(self, raw_line):
            return None

    stub = StubQueue()
    sup = Supervisor(
        coder=StubCoder(),
        queue=stub,
        runtime_toml_path=tmp_path / "runtime.toml",
        project_root=tmp_path,
        log=structlog.get_logger(),
    )
    sup._handle_outcome(
        ctx.task, TaskOutcomeRecord(outcome=TaskOutcome.SUCCESS, exit_code=0, reason="")
    )
    assert stub.blocked == [("epic-1", "needs creds")]


# ---------------------------------------------------------------------------
# Worker shape
# ---------------------------------------------------------------------------


def test_observer_pipeline_shape() -> None:
    names = [s.name for s in Observer.steps]
    assert Observer.name == "observer"
    assert names == ["wait_children", "collect_children", "llm_session", "spawn_followups"]


def test_plan_observer_builds_fresh_instances(tmp_path: Path) -> None:
    ctx, _ = _ctx(tmp_path)
    first = plan_observer(ctx)
    second = plan_observer(ctx)
    assert first.name == Observer.name == second.name
    assert [s.name for s in first.steps] == [s.name for s in second.steps]
    assert first.steps[2] is not second.steps[2]
