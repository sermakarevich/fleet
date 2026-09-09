"""Tests for workers/job.py. Mirrors the source path."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import structlog

from fleet.core.config import RuntimeConfig
from fleet.core.task import Task, TaskOutcome
from fleet.state import attempts
from fleet.state import paths as state_paths
from fleet.workers.base import StepContext, StepStatus
from fleet.workers.job import (
    JOB_GATE_CONTEXT,
    AskApproval,
    SpawnChildren,
    plan_job,
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


class FakeStore:
    """ask_human double: canned pending/answered, recorded asks."""

    def __init__(
        self,
        pending: list | None = None,
        answered: list | None = None,
    ) -> None:
        self._pending = pending or []
        self._answered = answered or []
        self.asked: list[dict] = []

    def ask(self, prompt, options, *, task_id=None, context=None, agent_id="job"):
        self.asked.append(
            {
                "prompt": prompt,
                "options": options,
                "task_id": task_id,
                "context": context,
                "agent_id": agent_id,
            }
        )
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


def _ctx(
    tmp_path: Path,
    task_id: str = "job-1",
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
            title="job",
            description="goal",
            status="in_progress",
            type="epic",
            worker="job",
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
# plan_job routing
# ---------------------------------------------------------------------------


def test_plan_job_research_first(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    worker = plan_job(ctx, FakeQueue())
    assert worker.name == "job.research"
    assert [s.name for s in worker.steps] == ["job_prepare", "llm_session"]


def test_plan_job_design_after_research(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    (ctx.task_dir / "artifacts").mkdir(parents=True, exist_ok=True)
    (ctx.task_dir / "artifacts" / "RESEARCH.md").write_text("research")
    worker = plan_job(ctx, FakeQueue())
    assert worker.name == "job.design"


def test_plan_job_gate_when_tasks_no_approval(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    (ctx.task_dir / "artifacts").mkdir(parents=True, exist_ok=True)
    (ctx.task_dir / "artifacts" / "RESEARCH.md").write_text("research")
    _write_tasks(ctx, _valid_tasks("t1"))
    worker = plan_job(ctx, FakeQueue())
    assert worker.name == "job.gate"
    assert [s.name for s in worker.steps] == ["ask_approval"]


def test_plan_job_spawn_when_approved(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    (ctx.task_dir / "artifacts").mkdir(parents=True, exist_ok=True)
    (ctx.task_dir / "artifacts" / "RESEARCH.md").write_text("research")
    _write_tasks(ctx, _valid_tasks("t1"))
    (ctx.task_dir / "artifacts" / "APPROVED").write_text("approved\n")
    worker = plan_job(ctx, FakeQueue())
    assert worker.name == "job.spawn"


def test_plan_job_spawn_when_gate_off(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, job_gate="off")
    (ctx.task_dir / "artifacts").mkdir(parents=True, exist_ok=True)
    (ctx.task_dir / "artifacts" / "RESEARCH.md").write_text("research")
    _write_tasks(ctx, _valid_tasks("t1"))
    worker = plan_job(ctx, FakeQueue())
    assert worker.name == "job.spawn"


def test_plan_job_observe_when_children_exist(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    (ctx.task_dir / "artifacts").mkdir(parents=True, exist_ok=True)
    (ctx.task_dir / "artifacts" / "RESEARCH.md").write_text("research")
    _write_tasks(ctx, _valid_tasks("t1"))
    queue = FakeQueue([{"id": "kid-1", "status": "open"}])
    worker = plan_job(ctx, queue)
    assert worker.name == "job.observe"
    assert [s.name for s in worker.steps] == [
        "wait_children",
        "collect_children",
        "llm_session",
        "spawn_followups",
    ]


def test_plan_job_blocks_after_two_research_failures(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, attempt_n=99)
    for _ in range(2):
        n = attempts.record_start(ctx.task_dir, coder="c", model="m", worker="job.research")
        attempts.record_end(
            ctx.task_dir,
            outcome="failure",
            exit_code=1,
            reason="boom",
            action="release",
            n=n,
        )
    worker = plan_job(ctx, FakeQueue())
    assert worker.name == "job.blocked"


def test_plan_job_partial_research_does_not_block(tmp_path: Path) -> None:
    # A research attempt ending PARTIAL succeeded — it must move forward.
    ctx = _ctx(tmp_path, attempt_n=99)
    for _ in range(2):
        n = attempts.record_start(ctx.task_dir, coder="c", model="m", worker="job.research")
        attempts.record_end(
            ctx.task_dir,
            outcome="partial",
            exit_code=0,
            reason="design",
            action="release",
            n=n,
        )
    worker = plan_job(ctx, FakeQueue())
    assert worker.name == "job.research"


# ---------------------------------------------------------------------------
# AskApproval
# ---------------------------------------------------------------------------


def test_gate_posts_question_and_waits(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    _write_tasks(ctx, _valid_tasks("t1", "t2"))
    store = FakeStore()
    result = asyncio.run(AskApproval(store).run(ctx))
    assert result.status == StepStatus.OUTCOME
    assert result.outcome is not None
    assert result.outcome.outcome == TaskOutcome.WAITING
    assert len(store.asked) == 1
    asked = store.asked[0]
    assert asked["task_id"] == "job-1"
    assert asked["context"] == JOB_GATE_CONTEXT
    assert "2 tasks" in asked["prompt"]


def test_gate_waits_on_pending_question(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    _write_tasks(ctx, _valid_tasks("t1"))
    store = FakeStore(pending=[{"id": "q1"}])
    result = asyncio.run(AskApproval(store).run(ctx))
    assert result.status == StepStatus.OUTCOME
    assert result.outcome.outcome == TaskOutcome.WAITING
    assert store.asked == []


def test_gate_approve_writes_marker(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    _write_tasks(ctx, _valid_tasks("t1"))
    store = FakeStore(answered=[{"id": "q1", "answer": "approve", "note": None}])
    result = asyncio.run(AskApproval(store).run(ctx))
    assert result.status == StepStatus.OK
    assert (ctx.task_dir / "artifacts" / "APPROVED").exists()
    declared = json.loads((ctx.task_dir / "RESULT.json").read_text(encoding="utf-8"))
    assert declared["status"] == "partial" and declared["next_step"] == "spawn"


def test_gate_revise_appends_note_and_deletes_tasks(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    _write_tasks(ctx, _valid_tasks("t1"))
    store = FakeStore(answered=[{"id": "q1", "answer": "revise (write note)", "note": "split t1"}])
    result = asyncio.run(AskApproval(store).run(ctx))
    assert result.status == StepStatus.OK
    assert not (ctx.task_dir / "artifacts" / "tasks.json").exists()
    notes = (ctx.task_dir / "artifacts" / "DESIGN_NOTES.md").read_text(encoding="utf-8")
    assert "split t1" in notes
    declared = json.loads((ctx.task_dir / "RESULT.json").read_text(encoding="utf-8"))
    assert declared["status"] == "partial" and declared["next_step"] == "design"


def test_gate_cancel_blocks(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    _write_tasks(ctx, _valid_tasks("t1"))
    store = FakeStore(answered=[{"id": "q1", "answer": "cancel job", "note": None}])
    result = asyncio.run(AskApproval(store).run(ctx))
    assert result.status == StepStatus.OK
    declared = json.loads((ctx.task_dir / "RESULT.json").read_text(encoding="utf-8"))
    assert declared["status"] == "blocked"
    assert declared["blocked_reason"] == "cancelled by operator"


def test_gate_invalid_tasks_skips_question(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    _write_tasks(ctx, {"tasks": [{"key": "a", "title": "", "body": ""}]})
    store = FakeStore()
    result = asyncio.run(AskApproval(store).run(ctx))
    assert result.status == StepStatus.OK
    assert store.asked == []
    assert (ctx.task_dir / "artifacts" / "DESIGN_ERRORS.md").exists()
    declared = json.loads((ctx.task_dir / "RESULT.json").read_text(encoding="utf-8"))
    assert declared["next_step"] == "design"


# ---------------------------------------------------------------------------
# SpawnChildren
# ---------------------------------------------------------------------------


def test_spawn_creates_children_with_deps_and_footer(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    (ctx.task_dir / "artifacts").mkdir(parents=True, exist_ok=True)
    (ctx.task_dir / "artifacts" / "DESIGN.md").write_text("design")
    _write_tasks(
        ctx,
        {
            "tasks": [
                {"key": "t1", "title": "one", "body": "do one", "depends_on": []},
                {"key": "t2", "title": "two", "body": "do two", "depends_on": ["t1"]},
            ]
        },
    )
    queue = FakeQueue()
    result = asyncio.run(SpawnChildren(queue).run(ctx))
    assert result.status == StepStatus.OK
    assert [spec["title"] for _, spec in queue.created] == ["one", "two"]
    assert queue.created[0][1]["depends_on"] == []
    assert queue.created[1][1]["depends_on"] == ["kid-1"]
    assert "Part of job job-1" in queue.created[0][1]["body"]
    journal = json.loads((ctx.task_dir / "artifacts" / "children.json").read_text(encoding="utf-8"))
    assert journal == {"t1": "kid-1", "t2": "kid-2"}
    assert queue.comments == [("job-1", "[fleet] job spawned 2 children: kid-1, kid-2")]
    declared = json.loads((ctx.task_dir / "RESULT.json").read_text(encoding="utf-8"))
    assert declared["status"] == "partial" and declared["next_step"] == "observe"


def test_spawn_resumes_without_duplicates(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    _write_tasks(ctx, _valid_tasks("t1", "t2"))
    (ctx.task_dir / "artifacts" / "children.json").write_text(json.dumps({"t1": "kid-old"}))
    queue = FakeQueue()
    result = asyncio.run(SpawnChildren(queue).run(ctx))
    assert result.status == StepStatus.OK
    # Only t2 is created; t1 keeps its earlier id.
    assert [spec["title"] for _, spec in queue.created] == ["title t2"]
    journal = json.loads((ctx.task_dir / "artifacts" / "children.json").read_text(encoding="utf-8"))
    assert journal == {"t1": "kid-old", "t2": "kid-1"}


def test_spawn_invalid_tasks_writes_errors(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    _write_tasks(ctx, {"tasks": "nope"})
    queue = FakeQueue()
    result = asyncio.run(SpawnChildren(queue).run(ctx))
    assert result.status == StepStatus.OK
    assert queue.created == []
    assert (ctx.task_dir / "artifacts" / "DESIGN_ERRORS.md").exists()
    declared = json.loads((ctx.task_dir / "RESULT.json").read_text(encoding="utf-8"))
    assert declared["next_step"] == "design"
