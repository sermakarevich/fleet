"""Each job phase step in isolation with a fake context.

Complements tests/workers/test_job.py (which covers plan_job routing and
gate/spawn behaviour end to end): here every step in workers/job.py runs
alone against a minimal fake StepContext, proving the ADR 0003 pipeline
shape — steps read declared config fields and ctx.plan, never private
attributes set from outside.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import structlog

from fleet.core.config import RuntimeConfig
from fleet.core.task import Task, TaskOutcome
from fleet.state.paths import task_dir as _task_dir
from fleet.workers.base import StepContext
from fleet.workers.job import AskApproval, BlockJob, JobPrepare, SpawnChildren


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


class FakeStore:
    """ask_human double: canned pending/answered, recorded asks."""

    def __init__(self, pending: list | None = None, answered: list | None = None) -> None:
        self._pending = pending or []
        self._answered = answered or []

    def ask(self, prompt, options, *, task_id=None, context=None, agent_id="job"):
        return "q1"

    def fetch_pending_for_task(self, task_id, context=None):
        return self._pending

    def fetch_answered_for_task(self, task_id, context=None):
        return self._answered


class StubCoder:
    name = "stub"

    def build_argv(self, task, task_dir, plan=None):
        return ["echo"]

    def env(self, task, task_dir):
        return {}

    def normalize_event(self, raw_line):
        return None

    def write_runtime_config(self, project, task):
        return None


def _ctx(tmp_path: Path, task_id: str = "job-1") -> StepContext:
    task_dir = _task_dir(tmp_path, task_id)
    task_dir.mkdir(parents=True, exist_ok=True)
    return StepContext(
        task=Task(
            id=task_id,
            title="job",
            description="goal",
            status="in_progress",
            type="epic",
            worker="job",
        ),
        task_dir=task_dir,
        project_root=tmp_path,
        fleet_home=tmp_path,
        coder=StubCoder(),  # type: ignore[arg-type]
        config=RuntimeConfig(),
        rate_gauge=None,  # type: ignore[arg-type]
        log=structlog.get_logger(),
        attempt_dir=task_dir / "attempts" / "1",
        attempt_n=1,
    )


def _write_tasks(ctx: StepContext, doc: dict) -> None:
    artifacts = ctx.task_dir / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    (artifacts / "tasks.json").write_text(json.dumps(doc))


def _valid_tasks(*keys: str) -> dict:
    return {
        "tasks": [
            {"key": k, "title": f"title {k}", "body": f"body {k}", "depends_on": []} for k in keys
        ]
    }


def test_job_prepare_sets_typed_plan(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    result = asyncio.run(JobPrepare("research").run(ctx))
    assert result.status == "ok"
    assert ctx.plan is not None and ctx.plan.mode == "research"
    assert ctx.scratch["launch_plan"] is ctx.plan
    run = json.loads((ctx.attempt_dir / "run.json").read_text(encoding="utf-8"))
    assert run["launch"]["mode"] == "research"


def test_job_prepare_design_packs_research_notes(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    artifacts = ctx.task_dir / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    (artifacts / "RESEARCH.md").write_text("findings")
    result = asyncio.run(JobPrepare("design").run(ctx))
    assert result.status == "ok"
    assert ctx.plan is not None and "findings" in ctx.plan.pack


def test_ask_approval_uses_declared_config(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    ctx.config = RuntimeConfig(job_max_children=1)
    _write_tasks(ctx, _valid_tasks("a", "b"))  # 2 tasks > cap of 1
    result = asyncio.run(AskApproval(lambda home: FakeStore()).run(ctx))
    assert result.status == "ok"
    declared = json.loads((ctx.task_dir / "RESULT.json").read_text(encoding="utf-8"))
    assert declared["next_step"] == "design"


def test_ask_approval_waits_for_gate(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    _write_tasks(ctx, _valid_tasks("a"))
    result = asyncio.run(AskApproval(lambda home: FakeStore()).run(ctx))
    assert result.status == "outcome"
    assert result.outcome is not None
    assert result.outcome.outcome == TaskOutcome.WAITING


def test_spawn_children_isolated(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    _write_tasks(ctx, _valid_tasks("a"))
    queue = FakeQueue()
    result = asyncio.run(SpawnChildren(lambda home: queue).run(ctx))
    assert result.status == "ok"
    assert [spec["title"] for _, spec in queue.created] == ["title a"]
    declared = json.loads((ctx.task_dir / "RESULT.json").read_text(encoding="utf-8"))
    assert declared["next_step"] == "observe"


def test_block_job_isolated(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    result = asyncio.run(BlockJob("too many failures").run(ctx))
    assert result.status == "ok"
    declared = json.loads((ctx.task_dir / "RESULT.json").read_text(encoding="utf-8"))
    assert declared["status"] == "blocked"
    assert declared["blocked_reason"] == "too many failures"
