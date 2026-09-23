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
import threading
from pathlib import Path
from types import SimpleNamespace

import structlog

from fleet.core.config import RuntimeConfig
from fleet.core.errors import WorkflowInvalid, WorkflowSourceUnavailable
from fleet.core.task import Task, TaskOutcome
from fleet.state import paths as state_paths
from fleet.state.spawn_journal import spawn_complete
from fleet.workers.base import RunHandle, StepContext, StepStatus
from fleet.workers.job import (
    _DEFER_MAX_ATTEMPTS,
    AskApproval,
    BlockJob,
    JobPrepare,
    SpawnChildren,
    _normalize_task,
)


class FakeQueue:
    """Queue double: canned children, recorded creates/comments/dependencies."""

    def __init__(self, children: list | None = None) -> None:
        self._children = children or []
        self.created: list[tuple[str, dict]] = []
        self.comments: list[tuple[str, str]] = []
        self.updated: list[tuple[str, str]] = []
        self.dependencies: list[tuple[str, str]] = []

    def list_children(self, epic_id: str):
        return self._children

    def create_child(self, epic_id: str, spec: dict):
        child_id = f"kid-{len(self.created) + 1}"
        self.created.append((epic_id, spec))
        return SimpleNamespace(id=child_id)

    def comment(self, task_id: str, body: str) -> None:
        self.comments.append((task_id, body))

    def update_task(self, task_id: str, *, description: str | None = None, **kwargs) -> None:
        self.updated.append((task_id, description or ""))

    def add_dependency(self, epic_id: str, child_id: str) -> None:
        self.dependencies.append((epic_id, child_id))


class FakeWorkflowRunner:
    """WorkflowRunnerLike double: returns a canned handle, records calls."""

    def __init__(self, handle=None, error: Exception | None = None) -> None:
        self.handle = handle
        self.error = error
        self.calls: list[tuple[str, dict]] = []

    def start(self, workflow_ref: str, inputs, *, parent_run_id=None, parent_task_id=None):
        self.calls.append((workflow_ref, dict(inputs)))
        if self.error is not None:
            raise self.error
        return self.handle


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


def _ctx(tmp_path: Path, task_id: str = "job-1", workflow_runner=None) -> StepContext:
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
        ),
        task_dir=task_dir,
        workdir=tmp_path,
        fleet_home=tmp_path,
        coder=StubCoder(),  # type: ignore[arg-type]
        config=RuntimeConfig(),
        rate_gauge=None,  # type: ignore[arg-type]
        log=structlog.get_logger(),
        attempt_dir=task_dir / "attempts" / "1",
        attempt_n=1,
        workflow_runner=workflow_runner,
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
    assert result.status == StepStatus.OK
    assert ctx.plan is not None and ctx.plan.mode == "research"
    assert ctx.launch_plan is ctx.plan
    run = json.loads((ctx.attempt_dir / "run.json").read_text(encoding="utf-8"))
    assert run["launch"]["mode"] == "research"


def test_job_prepare_design_packs_research_notes(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    artifacts = ctx.task_dir / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    (artifacts / "RESEARCH.md").write_text("findings")
    result = asyncio.run(JobPrepare("design").run(ctx))
    assert result.status == StepStatus.OK
    assert ctx.plan is not None and "findings" in ctx.plan.pack


def test_ask_approval_uses_declared_config(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    ctx.config = RuntimeConfig(job_max_children=1)
    _write_tasks(ctx, _valid_tasks("a", "b"))  # 2 tasks > cap of 1
    result = asyncio.run(AskApproval(FakeStore()).run(ctx))
    assert result.status == StepStatus.OK
    declared = json.loads((ctx.task_dir / "RESULT.json").read_text(encoding="utf-8"))
    assert declared["next_step"] == "design"


def test_ask_approval_waits_for_gate(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    _write_tasks(ctx, _valid_tasks("a"))
    result = asyncio.run(AskApproval(FakeStore()).run(ctx))
    assert result.status == StepStatus.OUTCOME
    assert result.outcome is not None
    assert result.outcome.outcome == TaskOutcome.WAITING


def test_spawn_children_isolated(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    _write_tasks(ctx, _valid_tasks("a"))
    queue = FakeQueue()
    result = asyncio.run(SpawnChildren(queue).run(ctx))
    assert result.status == StepStatus.OK
    assert [spec["title"] for _, spec in queue.created] == ["title a"]
    declared = json.loads((ctx.task_dir / "RESULT.json").read_text(encoding="utf-8"))
    assert declared["next_step"] == "observe"


def _workflow_tasks_doc() -> dict:
    return {
        "tasks": [
            {
                "key": "src-03",
                "title": "summarise: a title",
                "workflow": "summarise",
                "inputs": {"url": "https://example.com"},
            },
            {
                "key": "sib",
                "title": "sibling",
                "body": "sibling body",
                "depends_on": ["src-03"],
            },
        ]
    }


def test_spawn_children_workflow_child(tmp_path: Path) -> None:
    runner = FakeWorkflowRunner(handle=RunHandle("run-1", ("t1", "t2", "t3"), ("t3",)))
    ctx = _ctx(tmp_path, workflow_runner=runner)
    _write_tasks(ctx, _workflow_tasks_doc())
    queue = FakeQueue()
    result = asyncio.run(SpawnChildren(queue).run(ctx))
    assert result.status == StepStatus.OK
    # Only the run's last stage is wired: its earlier steps are its own deps.
    assert queue.dependencies == [("job-1", "t3")]
    children = json.loads((ctx.task_dir / "artifacts" / "children.json").read_text())
    assert children["src-03"] == "run-1"
    runs = json.loads((ctx.task_dir / "artifacts" / "children_runs.json").read_text())
    assert runs["src-03"] == {
        "run_id": "run-1",
        "task_ids": ["t1", "t2", "t3"],
        "final_task_ids": ["t3"],
    }
    sib_spec = next(spec for _, spec in queue.created if spec["title"] == "sibling")
    assert sib_spec["depends_on"] == ["t3"]
    assert runner.calls == [("summarise", {"url": "https://example.com"})]


def test_spawn_children_skips_failed_builder_and_its_dependents(tmp_path: Path) -> None:
    """A dead source skips its run and the copy that needed it; the rest proceed."""
    runner = FakeWorkflowRunner(error=WorkflowInvalid(["builder summarise: yt failed"]))
    ctx = _ctx(tmp_path, workflow_runner=runner)
    doc = _workflow_tasks_doc()
    doc["tasks"].append({"key": "solo", "title": "solo", "body": "solo body", "depends_on": []})
    doc["tasks"].append(
        {"key": "agg", "title": "agg", "body": "agg body", "depends_on": ["sib", "solo"]}
    )
    _write_tasks(ctx, doc)
    queue = FakeQueue()
    result = asyncio.run(SpawnChildren(queue).run(ctx))
    assert result.status == StepStatus.OK
    skipped = json.loads((ctx.task_dir / "artifacts" / "children_skipped.json").read_text())
    assert "yt failed" in skipped["src-03"]
    assert "src-03" in skipped["sib"]
    children = json.loads((ctx.task_dir / "artifacts" / "children.json").read_text())
    assert set(children) == {"solo", "agg"}
    agg_spec = next(spec for _, spec in queue.created if spec["title"] == "agg")
    assert agg_spec["depends_on"] == [children["solo"]]
    assert queue.dependencies == []
    assert "skipped 2" in queue.comments[-1][1]


def test_spawn_children_defers_a_transient_source_instead_of_skipping(tmp_path: Path) -> None:
    """A rate limit must not write the source off; the key is left for a retry."""
    runner = FakeWorkflowRunner(
        error=WorkflowSourceUnavailable(["builder summarise: rate limited; retry later"])
    )
    ctx = _ctx(tmp_path, workflow_runner=runner)
    doc = _workflow_tasks_doc()
    doc["tasks"].append({"key": "solo", "title": "solo", "body": "solo body", "depends_on": []})
    _write_tasks(ctx, doc)
    queue = FakeQueue()
    result = asyncio.run(SpawnChildren(queue).run(ctx))
    assert result.status == StepStatus.OK
    artifacts = ctx.task_dir / "artifacts"
    # Nothing skipped: children_skipped.json must not claim the source is dead.
    assert not (artifacts / "children_skipped.json").exists()
    deferred = json.loads((artifacts / "children_deferred.json").read_text())
    assert "rate limited" in deferred["src-03"]["reason"]
    assert deferred["src-03"]["attempts"] == 1
    # the copy that needs that source waits with it instead of being created
    assert "src-03" in deferred["sib"]["reason"]
    children = json.loads((artifacts / "children.json").read_text())
    assert set(children) == {"solo"}
    # spawn is not finished, so the epic stays claimable and retries the keys
    assert not spawn_complete(ctx.task_dir)
    assert "deferred 2" in queue.comments[-1][1]


def test_spawn_children_retries_a_deferred_key_on_the_next_attempt(tmp_path: Path) -> None:
    """Once the source answers again, the deferred key spawns normally."""
    blocked = FakeWorkflowRunner(
        error=WorkflowSourceUnavailable(["builder summarise: rate limited; retry later"])
    )
    ctx = _ctx(tmp_path, workflow_runner=blocked)
    _write_tasks(ctx, _workflow_tasks_doc())
    asyncio.run(SpawnChildren(FakeQueue()).run(ctx))

    ok = FakeWorkflowRunner(handle=RunHandle("run-1", ("t1", "t2", "t3"), ("t3",)))
    ctx = _ctx(tmp_path, workflow_runner=ok)
    result = asyncio.run(SpawnChildren(FakeQueue()).run(ctx))
    assert result.status == StepStatus.OK
    assert ok.calls, "the deferred key must be tried again"
    children = json.loads((ctx.task_dir / "artifacts" / "children.json").read_text())
    assert children["src-03"] == "run-1"
    assert json.loads((ctx.task_dir / "artifacts" / "children_deferred.json").read_text()) == {}


def test_spawn_children_skips_a_key_that_stays_unreachable(tmp_path: Path) -> None:
    """The retry budget runs out, so a source nobody can read stops blocking the job."""
    runner = FakeWorkflowRunner(
        error=WorkflowSourceUnavailable(["builder summarise: no transcript offered"])
    )
    artifacts = None
    for attempt in range(_DEFER_MAX_ATTEMPTS):
        ctx = _ctx(tmp_path, workflow_runner=runner)
        _write_tasks(ctx, _workflow_tasks_doc())
        artifacts = ctx.task_dir / "artifacts"
        artifacts.mkdir(parents=True, exist_ok=True)
        (artifacts / "children.json").write_text(json.dumps({"done": "kid-0"}))
        asyncio.run(SpawnChildren(FakeQueue()).run(ctx))
        deferred = json.loads((artifacts / "children_deferred.json").read_text())
        if attempt < _DEFER_MAX_ATTEMPTS - 1:
            assert deferred["src-03"]["attempts"] == attempt + 1
    assert artifacts is not None
    skipped = json.loads((artifacts / "children_skipped.json").read_text())
    assert f"unreachable on {_DEFER_MAX_ATTEMPTS} attempts" in skipped["src-03"]
    assert "src-03" not in json.loads((artifacts / "children_deferred.json").read_text())


def test_spawn_children_blocks_when_an_attempt_makes_no_progress(tmp_path: Path) -> None:
    """All that is left is unreachable: block rather than spin on the same host."""
    blocked = FakeWorkflowRunner(
        error=WorkflowSourceUnavailable(["builder summarise: rate limited; retry later"])
    )
    ctx = _ctx(tmp_path, workflow_runner=blocked)
    _write_tasks(ctx, _workflow_tasks_doc())
    artifacts = ctx.task_dir / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    (artifacts / "children.json").write_text(json.dumps({"done": "kid-0"}))

    result = asyncio.run(SpawnChildren(FakeQueue()).run(ctx))
    assert result.status == StepStatus.OK
    written = json.loads((ctx.task_dir / "RESULT.json").read_text())
    assert written["status"] == "blocked"
    assert "children_deferred.json" in written["blocked_reason"]


def test_spawn_children_all_skipped_fails(tmp_path: Path) -> None:
    runner = FakeWorkflowRunner(error=WorkflowInvalid(["builder summarise: yt failed"]))
    ctx = _ctx(tmp_path, workflow_runner=runner)
    _write_tasks(ctx, _workflow_tasks_doc())
    result = asyncio.run(SpawnChildren(FakeQueue()).run(ctx))
    assert result.status == StepStatus.FAIL
    assert "every task was skipped" in result.reason


def test_spawn_children_workflow_without_runner_fails(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, workflow_runner=None)
    _write_tasks(ctx, _workflow_tasks_doc())
    queue = FakeQueue()
    result = asyncio.run(SpawnChildren(queue).run(ctx))
    assert result.status == StepStatus.FAIL
    assert "workflow runner" in result.reason


def test_spawn_children_workflow_journal_is_idempotent(tmp_path: Path) -> None:
    runner = FakeWorkflowRunner(handle=RunHandle("run-1", ("t1", "t2", "t3"), ("t3",)))
    ctx = _ctx(tmp_path, workflow_runner=runner)
    _write_tasks(ctx, _workflow_tasks_doc())
    artifacts = ctx.task_dir / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    (artifacts / "children.json").write_text(json.dumps({"src-03": "run-1"}))
    (artifacts / "children_runs.json").write_text(
        json.dumps(
            {
                "src-03": {
                    "run_id": "run-1",
                    "task_ids": ["t1", "t2", "t3"],
                    "final_task_ids": ["t3"],
                }
            }
        )
    )
    queue = FakeQueue()
    result = asyncio.run(SpawnChildren(queue).run(ctx))
    assert result.status == StepStatus.OK
    assert runner.calls == []
    assert queue.dependencies == [("job-1", "t3")]


def test_normalize_task_keeps_workflow_and_inputs() -> None:
    normalized = _normalize_task(
        {
            "key": "src-03",
            "title": "summarise: a title",
            "workflow": "summarise",
            "inputs": {"url": "https://example.com"},
        }
    )
    assert normalized["workflow"] == "summarise"
    assert normalized["inputs"] == {"url": "https://example.com"}


def test_normalize_task_defaults_workflow_and_inputs() -> None:
    normalized = _normalize_task({"key": "a", "title": "t", "body": "b"})
    assert normalized["workflow"] is None
    assert normalized["inputs"] == {}


def test_block_job_isolated(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    result = asyncio.run(BlockJob("too many failures").run(ctx))
    assert result.status == StepStatus.OK
    declared = json.loads((ctx.task_dir / "RESULT.json").read_text(encoding="utf-8"))
    assert declared["status"] == "blocked"
    assert declared["blocked_reason"] == "too many failures"


def test_spawn_children_starts_workflow_runs_concurrently(tmp_path: Path) -> None:
    """Workflow children start in parallel: a slow start must not block the others."""
    started = threading.Barrier(3, timeout=10)

    class BarrierRunner:
        """Each start waits for two siblings; serial starts would time out."""

        def __init__(self) -> None:
            self.calls: list[tuple[str, dict]] = []
            self._lock = threading.Lock()

        def start(self, workflow_ref: str, inputs, *, parent_run_id=None, parent_task_id=None):
            started.wait()
            with self._lock:
                self.calls.append((workflow_ref, dict(inputs)))
                n = len(self.calls)
            return RunHandle(f"run-{n}", (f"t{n}a", f"t{n}b"), (f"t{n}b",))

    runner = BarrierRunner()
    ctx = _ctx(tmp_path, workflow_runner=runner)
    _write_tasks(
        ctx,
        {
            "tasks": [
                {
                    "key": f"src-{i}",
                    "title": f"summarise {i}",
                    "workflow": "summarise",
                    "inputs": {"url": f"https://example.com/{i}"},
                }
                for i in range(3)
            ]
        },
    )
    result = asyncio.run(SpawnChildren(FakeQueue()).run(ctx))
    assert result.status == StepStatus.OK
    runs = json.loads((ctx.task_dir / "artifacts" / "children_runs.json").read_text())
    assert len(runs) == 3


def test_spawn_journals_starting_intent_before_start(tmp_path: Path) -> None:
    """The intent hits children_runs.json before runner.start runs.

    A spawn attempt killed mid-start leaves this breadcrumb instead of an
    orphan run nobody claims.
    """
    seen: dict = {}

    class IntentPeekingRunner:
        def start(self, workflow_ref: str, inputs, *, parent_run_id=None, parent_task_id=None):
            seen.update(json.loads((artifacts_dir / "children_runs.json").read_text()))
            return RunHandle("run-1", ("t1",), ("t1",))

    ctx = _ctx(tmp_path, workflow_runner=IntentPeekingRunner())
    _write_tasks(ctx, _workflow_tasks_doc())
    artifacts_dir = ctx.task_dir / "artifacts"
    result = asyncio.run(SpawnChildren(FakeQueue()).run(ctx))
    assert result.status == StepStatus.OK
    assert seen["src-03"]["status"] == "starting"
    assert seen["src-03"]["inputs"] == {"url": "https://example.com"}
    completed = json.loads((artifacts_dir / "children_runs.json").read_text())
    assert completed["src-03"]["run_id"] == "run-1"


def test_spawn_retries_stale_starting_intent_without_second_chain(tmp_path: Path) -> None:
    """A killed attempt's breadcrumb is retried; a deduping runner starts once."""
    orphan_inputs = {"url": "https://example.com"}

    class DedupeRunner:
        """Mimics WorkflowRunner's inputs dedupe: one run per input set."""

        def __init__(self) -> None:
            self.starts = 0
            self.known: dict = {}

        def start(self, workflow_ref: str, inputs, *, parent_run_id=None, parent_task_id=None):
            key = (workflow_ref, tuple(sorted(inputs.items())))
            if key not in self.known:
                self.starts += 1
                self.known[key] = RunHandle(
                    f"run-{self.starts}", (f"t{self.starts}",), (f"t{self.starts}",)
                )
            return self.known[key]

    runner = DedupeRunner()
    # Attempt 1: the run was created, but the attempt died after journaling
    # only the intent — the run is an orphan no journal claims.
    orphan = runner.start("summarise", orphan_inputs)
    ctx = _ctx(tmp_path, workflow_runner=runner)
    _write_tasks(ctx, _workflow_tasks_doc())
    artifacts = ctx.task_dir / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    (artifacts / "children_runs.json").write_text(
        json.dumps(
            {
                "src-03": {
                    "status": "starting",
                    "workflow": "summarise",
                    "inputs": dict(orphan_inputs),
                }
            }
        )
    )
    result = asyncio.run(SpawnChildren(FakeQueue()).run(ctx))
    assert result.status == StepStatus.OK
    assert runner.starts == 1, "the retry must reuse the orphan, not start again"
    runs = json.loads((artifacts / "children_runs.json").read_text())
    assert runs["src-03"]["run_id"] == orphan.run_id
    children = json.loads((artifacts / "children.json").read_text())
    assert children["src-03"] == orphan.run_id
