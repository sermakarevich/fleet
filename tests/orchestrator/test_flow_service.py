"""Tests for orchestrator/flow_service.py: tick drives runs end to end."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

from fleet.core.config import RuntimeConfig
from fleet.orchestrator import flow_coder as flow_coder_mod
from fleet.orchestrator import flow_service as flow_service_mod
from fleet.orchestrator.flow_service import make_flow_service, on_start, tick
from fleet.orchestrator.service import ServiceOrder
from fleet.runs import engine
from fleet.runs.run_dir import NO_ITEM, outputs_file
from fleet.runs.store import Run, RunStatus, StepRun, StepStatus
from fleet.workers.base import FnStep, StepResult, Worker
from fleet.workers.base import StepStatus as WorkerStepStatus
from tests.conftest import FakeQueue, make_supervisor
from tests.pool.conftest import FakeStore

NOW = datetime(2026, 9, 28, 7, 0, 0, tzinfo=UTC)

ECHOER_TOOL = """\
fleet_tool: 2
description: Print a fixed object.
command: ["python3", "-c", "import json; print(json.dumps({'n': 1}))"]
args: {}
env: []
output: json
timeout: 30
"""

FAILER_TOOL = """\
fleet_tool: 2
description: Always fail.
command: ["python3", "-c", "import sys; print('nope'); sys.exit(1)"]
args: {}
env: []
output: text
timeout: 30
"""

PASSER_TOOL = """\
fleet_tool: 2
description: Print its arg.
command: ["python3", "-c", "import sys; print(sys.argv[1])", "{{ args.v }}"]
args:
  v: {required: true}
env: []
output: text
timeout: 30
"""


class StubCoder:
    name = "stub"
    model = "stub-model"


def _catalog_dir(tmp_path: Path, flows: dict[str, str], tools: dict[str, str]) -> Path:
    root = tmp_path / "catalog"
    (root / "flows").mkdir(parents=True)
    (root / "tools").mkdir(parents=True)
    for name, text in flows.items():
        (root / "flows" / f"{name}.yaml").write_text(text, encoding="utf-8")
    for name, text in tools.items():
        (root / "tools" / f"{name}.yaml").write_text(text, encoding="utf-8")
    return root


def _state(tmp_path: Path, catalog: Path, **kw):
    config = RuntimeConfig(flows_folders=[str(catalog)], isolation="none")
    sup = make_supervisor(
        tmp_path,
        queue=kw.get("queue", FakeQueue()),
        config=config,
        coder=kw.get("coder", StubCoder()),  # type: ignore[arg-type]
        services=[],
        checks=[],
    )
    sup.state.question_store = kw.get("question_store")
    return sup.state


def _install_fake_worker(monkeypatch, seen: dict) -> None:
    async def _fake(ctx) -> StepResult:
        seen[ctx.attempt_n] = (ctx.attempt_dir / "prompt.md").read_text(encoding="utf-8")
        (ctx.task_dir / "outputs.json").write_text(json.dumps({}), encoding="utf-8")
        (ctx.task_dir / "RESULT.json").write_text(
            json.dumps({"schema": 1, "status": "done", "summary": "ok"}), encoding="utf-8"
        )
        return StepResult(status=WorkerStepStatus.OK, reason="")

    def _select(task, ctx, queue=None) -> Worker:
        return Worker(name="fake", steps=(FnStep(name="fake", fn=_fake),))

    monkeypatch.setattr(flow_coder_mod, "select_worker", _select)


async def _drive(st, run_id: str, limit: int = 60):
    """Tick until the run finishes; let in-flight tasks progress between ticks."""
    for _ in range(limit):
        await tick(st)
        inflight = [
            *st.flows.tools.values(),
            *st.flows.humans.values(),
            *(worker.future for worker in st.flows.coders.values()),
        ]
        if inflight:
            await asyncio.wait(inflight)
        run = st.flows.store.get_run(run_id)
        if run is not None and run.status is not RunStatus.running:
            return run
    raise AssertionError("run did not finish")


def _start(st, flow_name: str, inputs: dict | None = None) -> Run:
    flow = st.flows.catalog.flow(flow_name)
    return engine.start_run(st.flows.store, st.fleet_home, flow, inputs or {}, NOW)


def test_service_order_and_start(tmp_path: Path) -> None:
    """Flows sits between Claim and Reap; on_start fills st.flows."""
    svc = make_flow_service()
    assert svc.order == ServiceOrder.Flows == 25
    assert svc.interval_sec == 5.0
    catalog = _catalog_dir(tmp_path, {"demo": "fleet_flow: 2\nsteps:\n  a:\n    prompt: hi\n"}, {})
    st = _state(tmp_path, catalog)
    assert st.flows is None
    asyncio.run(on_start(st))
    assert st.flows.catalog.flows["demo"].name == "demo"
    assert st.flows.coders == {} and st.flows.tools == {} and st.flows.humans == {}


def test_tool_step_runs_to_succeeded(tmp_path: Path) -> None:
    """One tool step runs through on_start + ticks to succeeded with outputs."""
    catalog = _catalog_dir(
        tmp_path,
        {"demo": "fleet_flow: 2\nsteps:\n  a:\n    kind: tool\n    tool: echoer\n"},
        {"echoer": ECHOER_TOOL},
    )
    st = _state(tmp_path, catalog)
    asyncio.run(on_start(st))
    run = _start(st, "demo")
    finished = asyncio.run(_drive(st, run.id))
    assert finished.status is RunStatus.succeeded
    row = st.flows.store.get_step_run(run.id, "a", NO_ITEM)
    assert row is not None and row.status is StepStatus.succeeded
    step_dir = st.fleet_home / "runs" / run.id / "a"
    assert json.loads(outputs_file(step_dir).read_text(encoding="utf-8")) == {"n": 1}


def test_two_steps_pass_outputs(tmp_path: Path) -> None:
    """steps.a.outputs.n renders into the second step's tool args."""
    flow_yaml = """\
fleet_flow: 2
steps:
  a:
    kind: tool
    tool: echoer
  b:
    needs: [a]
    kind: tool
    tool: passer
    args: {v: "{{ steps.a.outputs.n }}"}
"""
    catalog = _catalog_dir(
        tmp_path, {"demo": flow_yaml}, {"echoer": ECHOER_TOOL, "passer": PASSER_TOOL}
    )
    st = _state(tmp_path, catalog)
    asyncio.run(on_start(st))
    run = _start(st, "demo")
    finished = asyncio.run(_drive(st, run.id))
    assert finished.status is RunStatus.succeeded
    step_dir = st.fleet_home / "runs" / run.id / "b"
    assert json.loads(outputs_file(step_dir).read_text(encoding="utf-8")) == {"result": "1\n"}


def test_after_check_retry_feedback_then_fail(tmp_path: Path, monkeypatch) -> None:
    """A failing after-check retries with feedback in prompt.md, then fails."""
    flow_yaml = """\
fleet_flow: 2
steps:
  draft:
    prompt: Write it
    retries: 1
    checks:
      - name: good
        tool: failer
        on_fail: retry
"""
    catalog = _catalog_dir(tmp_path, {"demo": flow_yaml}, {"failer": FAILER_TOOL})
    st = _state(tmp_path, catalog)
    asyncio.run(on_start(st))
    seen: dict = {}
    _install_fake_worker(monkeypatch, seen)
    run = _start(st, "demo")
    finished = asyncio.run(_drive(st, run.id))
    assert finished.status is RunStatus.failed
    row = st.flows.store.get_step_run(run.id, "draft", NO_ITEM)
    assert row is not None and row.status is StepStatus.failed and row.attempt == 2
    step_dir = st.fleet_home / "runs" / run.id / "draft"
    prompt2 = (step_dir / "attempts" / "2" / "prompt.md").read_text(encoding="utf-8")
    assert "Previous attempt failed check `good`" in prompt2
    assert "nope" in prompt2
    assert seen[2] == prompt2


def test_after_check_retry_zero_fails_at_once(tmp_path: Path, monkeypatch) -> None:
    """With retries: 0 the first failing after-check fails the row, no retry."""
    flow_yaml = """\
fleet_flow: 2
steps:
  draft:
    prompt: Write it
    retries: 0
    checks:
      - name: good
        tool: failer
        on_fail: retry
"""
    catalog = _catalog_dir(tmp_path, {"demo": flow_yaml}, {"failer": FAILER_TOOL})
    st = _state(tmp_path, catalog)
    asyncio.run(on_start(st))
    seen: dict = {}
    _install_fake_worker(monkeypatch, seen)
    run = _start(st, "demo")
    finished = asyncio.run(_drive(st, run.id))
    assert finished.status is RunStatus.failed
    row = st.flows.store.get_step_run(run.id, "draft", NO_ITEM)
    assert row is not None and row.status is StepStatus.failed and row.attempt == 1
    assert seen.keys() == {1}
    assert not (st.fleet_home / "runs" / run.id / "draft" / "attempts" / "2").exists()


def test_before_check_skip_continues(tmp_path: Path) -> None:
    """A failing before-check with on_fail: skip skips the row, the run goes on."""
    flow_yaml = """\
fleet_flow: 2
steps:
  a:
    kind: tool
    tool: echoer
    checks:
      - name: guard
        tool: failer
        when: before
        on_fail: skip
  b:
    needs: [a]
    kind: tool
    tool: echoer
"""
    catalog = _catalog_dir(
        tmp_path, {"demo": flow_yaml}, {"echoer": ECHOER_TOOL, "failer": FAILER_TOOL}
    )
    st = _state(tmp_path, catalog)
    asyncio.run(on_start(st))
    run = _start(st, "demo")
    finished = asyncio.run(_drive(st, run.id))
    assert finished.status is RunStatus.succeeded
    skipped = st.flows.store.get_step_run(run.id, "a", NO_ITEM)
    assert skipped is not None and skipped.status is StepStatus.skipped
    assert skipped.reason == "nope"
    ok_row = st.flows.store.get_step_run(run.id, "b", NO_ITEM)
    assert ok_row is not None and ok_row.status is StepStatus.succeeded


def test_capped_coder_waits_and_dispatches(tmp_path: Path, monkeypatch) -> None:
    """can_claim false holds the launch in waiting; the next tick dispatches it."""
    catalog = _catalog_dir(
        tmp_path, {"demo": "fleet_flow: 2\nsteps:\n  draft:\n    prompt: Write it\n"}, {}
    )
    st = _state(tmp_path, catalog)
    asyncio.run(on_start(st))
    seen: dict = {}
    _install_fake_worker(monkeypatch, seen)
    run = _start(st, "demo")
    monkeypatch.setattr(flow_service_mod, "can_claim", lambda st, coder: False)
    asyncio.run(tick(st))
    assert len(st.flows.waiting) == 1
    assert st.flows.coders == {}
    row = st.flows.store.get_step_run(run.id, "draft", NO_ITEM)
    assert row is not None and row.status is StepStatus.running and row.attempt == 1
    monkeypatch.setattr(flow_service_mod, "can_claim", lambda st, coder: True)
    asyncio.run(tick(st))
    assert st.flows.waiting == []
    assert len(st.flows.coders) == 1
    task_id = next(iter(st.flows.coders))
    assert task_id == f"{run.id}.draft"


def test_missing_flow_cancels_run(tmp_path: Path) -> None:
    """A running run whose flow left the catalog is cancelled."""
    catalog = _catalog_dir(tmp_path, {"demo": "fleet_flow: 2\nsteps:\n  a:\n    prompt: hi\n"}, {})
    st = _state(tmp_path, catalog)
    asyncio.run(on_start(st))
    store = st.flows.store
    store.create_run(
        Run(
            id="run-gone",
            flow="gone",
            status=RunStatus.running,
            inputs={},
            started_at=NOW.isoformat(),
        )
    )
    store.add_step_runs(
        [StepRun(run_id="run-gone", step="a", item_index=NO_ITEM, status=StepStatus.pending)]
    )
    asyncio.run(tick(st))
    finished = store.get_run("run-gone")
    assert finished is not None and finished.status is RunStatus.cancelled
    assert finished.reason == "flow no longer in catalog"


def test_human_step_answers_and_succeeds(tmp_path: Path) -> None:
    """A human step with a pre-answered FakeStore question succeeds with outputs."""
    catalog = _catalog_dir(
        tmp_path,
        {"demo": "fleet_flow: 2\nsteps:\n  answer:\n    kind: human\n    prompt: Continue?\n"},
        {},
    )
    questions = FakeStore()
    st = _state(tmp_path, catalog, question_store=questions)
    asyncio.run(on_start(st))
    run = _start(st, "demo")
    task_id = f"{run.id}.answer"
    qid = questions.ask("Continue?", ["yes", "no"], task_id=task_id, context="step:1")
    questions.answer(qid, "yes", note="go")
    finished = asyncio.run(_drive(st, run.id))
    assert finished.status is RunStatus.succeeded
    step_dir = st.fleet_home / "runs" / run.id / "answer"
    assert json.loads(outputs_file(step_dir).read_text(encoding="utf-8")) == {
        "answer": "yes",
        "note": "go",
        "question_id": qid,
    }


def test_unknown_tool_fails_step(tmp_path: Path) -> None:
    """A tool step naming no catalog tool fails with 'unknown tool'."""
    catalog = _catalog_dir(
        tmp_path, {"demo": "fleet_flow: 2\nsteps:\n  a:\n    kind: tool\n    tool: nope\n"}, {}
    )
    st = _state(tmp_path, catalog)
    asyncio.run(on_start(st))
    run = _start(st, "demo")
    finished = asyncio.run(_drive(st, run.id))
    assert finished.status is RunStatus.failed
    row = st.flows.store.get_step_run(run.id, "a", NO_ITEM)
    assert row is not None and row.status is StepStatus.failed
    assert "unknown tool nope" in row.reason
