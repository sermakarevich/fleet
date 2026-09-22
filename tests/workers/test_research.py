"""Tests for workers/research.py. Mirrors the source path."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import structlog

from fleet.core.config import RuntimeConfig
from fleet.core.plan_input import PlanInput
from fleet.core.task import Task
from fleet.state import paths as state_paths
from fleet.workers.base import StepContext
from fleet.workers.job import AskApproval
from fleet.workers.research import plan_research

from .test_job import FakeQueue, FakeStore, StubCoder


def _ctx(
    tmp_path: Path,
    task_id: str = "research-1",
    *,
    job_gate: str | None = None,
    attempt_n: int = 1,
    config: RuntimeConfig | None = None,
) -> StepContext:
    task_dir = state_paths.task_dir(tmp_path, task_id)
    task_dir.mkdir(parents=True, exist_ok=True)
    return StepContext(
        task=Task(
            id=task_id,
            title="research topic",
            description="topics: agentic memory\nfocus: ...\ntarget: agentic-memory",
            status="in_progress",
            type="epic",
            worker="research",
            job_gate=job_gate,
        ),
        task_dir=task_dir,
        workdir=tmp_path,
        fleet_home=tmp_path,
        coder=StubCoder(),  # type: ignore[arg-type]
        config=config or RuntimeConfig(),
        rate_gauge=None,  # type: ignore[arg-type]
        log=structlog.get_logger(),
        attempt_dir=task_dir / "attempts" / str(attempt_n),
        attempt_n=attempt_n,
    )


def _plan(ctx: StepContext) -> PlanInput:
    return PlanInput(
        task=ctx.task, task_dir=ctx.task_dir, config=ctx.config, attempt_n=ctx.attempt_n
    )


def _valid_tasks(*keys: str) -> dict:
    return {
        "tasks": [
            {"key": k, "title": f"title {k}", "body": f"body {k}", "depends_on": []} for k in keys
        ]
    }


def _write_tasks(ctx: StepContext, doc: dict) -> None:
    artifacts = ctx.task_dir / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    (artifacts / "tasks.json").write_text(json.dumps(doc))


# ---------------------------------------------------------------------------
# plan_research phase progression
# ---------------------------------------------------------------------------


def test_plan_research_discover_first(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    worker = plan_research(_plan(ctx), FakeQueue())
    assert worker.name == "research.discover"
    assert [s.name for s in worker.steps] == ["job_prepare", "llm_session"]


def test_plan_research_design_after_research(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    (ctx.task_dir / "artifacts").mkdir(parents=True, exist_ok=True)
    (ctx.task_dir / "artifacts" / "RESEARCH.md").write_text("research")
    worker = plan_research(_plan(ctx), FakeQueue())
    assert worker.name == "research.design"


def test_plan_research_gate_when_tasks_no_approval(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    (ctx.task_dir / "artifacts").mkdir(parents=True, exist_ok=True)
    (ctx.task_dir / "artifacts" / "RESEARCH.md").write_text("research")
    _write_tasks(ctx, _valid_tasks("t1"))
    worker = plan_research(_plan(ctx), FakeQueue())
    assert worker.name == "job.gate"
    assert [s.name for s in worker.steps] == ["ask_approval"]


def test_plan_research_spawn_when_approved(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    (ctx.task_dir / "artifacts").mkdir(parents=True, exist_ok=True)
    (ctx.task_dir / "artifacts" / "RESEARCH.md").write_text("research")
    _write_tasks(ctx, _valid_tasks("t1"))
    (ctx.task_dir / "artifacts" / "APPROVED").write_text("approved\n")
    worker = plan_research(_plan(ctx), FakeQueue())
    assert worker.name == "job.spawn"


def test_plan_research_observe_when_children_exist(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    (ctx.task_dir / "artifacts").mkdir(parents=True, exist_ok=True)
    (ctx.task_dir / "artifacts" / "RESEARCH.md").write_text("research")
    _write_tasks(ctx, _valid_tasks("t1"))
    queue = FakeQueue([{"id": "kid-1", "status": "open"}])
    worker = plan_research(_plan(ctx), queue)
    assert worker.name == "job.observe"
    assert [s.name for s in worker.steps] == [
        "wait_children",
        "collect_children",
        "llm_session",
        "spawn_followups",
    ]


# ---------------------------------------------------------------------------
# research_design launch pack includes candidates.json
# ---------------------------------------------------------------------------


def test_design_pack_includes_research_and_candidates(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    artifacts = ctx.task_dir / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    (artifacts / "RESEARCH.md").write_text("# shortlist\n1. paper A")
    (artifacts / "candidates.json").write_text('{"inputs": {}, "candidates": []}')
    worker = plan_research(_plan(ctx), FakeQueue())
    assert worker.name == "research.design"
    prepare = worker.steps[0]
    asyncio.run(prepare.run(ctx))
    assert ctx.launch_plan is not None
    assert "shortlist" in ctx.launch_plan.pack
    assert "candidates" in ctx.launch_plan.pack


# ---------------------------------------------------------------------------
# gate prompt shows RESEARCH.md instead of task titles
# ---------------------------------------------------------------------------


def test_research_gate_prompt_shows_research_md(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    artifacts = ctx.task_dir / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    (artifacts / "RESEARCH.md").write_text("# ranked shortlist\n1 | paper | 0.9 | Title | topic-a")
    _write_tasks(ctx, _valid_tasks("t1", "t2"))
    store = FakeStore()
    result = asyncio.run(AskApproval(store, research=True).run(ctx))
    assert result.status.name == "OUTCOME"
    asked = store.asked[0]
    assert "ranked shortlist" in asked["prompt"]
    assert "approve 2 tasks?" in asked["prompt"]
    assert asked["options"] == ["approve", "revise (write note)", "cancel job"]
