"""Store tests: workflows, runs, step runs, and schema migration."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from fleet.core.errors import WorkflowNameTaken
from fleet.workflows.model import (
    Defaults,
    RunStatus,
    Stage,
    Step,
    StepRun,
    Trigger,
    Workflow,
    WorkflowRun,
)
from fleet.workflows.store import SCHEMA_VERSION, WorkflowStore


def _workflow(name: str = "demo", wid: str = "wf-test0001") -> Workflow:
    """Build a small valid workflow for store tests."""
    return Workflow(
        id=wid,
        name=name,
        description="d",
        defaults=Defaults(),
        stages=(
            Stage(name="first", steps=(Step(name="collect", title="Collect"),)),
            Stage(name="second", steps=(Step(name="report", title="Report"),)),
        ),
        created_at="2026-09-09T00:00:00Z",
        updated_at="2026-09-09T00:00:00Z",
    )


def _run(wid: str, rid: str, n: int, started: str) -> WorkflowRun:
    """Build one run row for store tests."""
    return WorkflowRun(
        id=rid,
        workflow_id=wid,
        n=n,
        trigger=Trigger.manual,
        schedule_id=None,
        spec=_workflow(),
        status=RunStatus.running,
        started_at=started,
    )


def test_save_get_list_delete_cascade(tmp_path: Path) -> None:
    store = WorkflowStore(tmp_path / "w.db")
    store.save(_workflow())
    assert store.get("wf-test0001") == _workflow()
    assert store.get_by_name("demo") == _workflow()
    assert [w.name for w in store.list()] == ["demo"]

    run = _run("wf-test0001", "wfr-00000001", 1, "2026-09-09T01:00:00Z")
    store.save_run(run)
    store.save_step_runs(
        [
            StepRun(
                run_id=run.id,
                step_name="collect",
                stage_index=0,
                task_id="t1",
                task_status="open",
                updated_at="2026-09-09T01:00:00Z",
            )
        ]
    )
    assert store.delete("wf-test0001") is True
    assert store.get("wf-test0001") is None
    assert store.get_run(run.id) is None
    assert store.step_runs(run.id) == []
    store.close()


def test_save_name_taken(tmp_path: Path) -> None:
    store = WorkflowStore(tmp_path / "w.db")
    store.save(_workflow(name="demo", wid="wf-aaaa0001"))
    with pytest.raises(WorkflowNameTaken):
        store.save(_workflow(name="demo", wid="wf-bbbb0002"))
    store.save(_workflow(name="demo", wid="wf-aaaa0001"))  # same id replaces
    store.close()


def test_list_orders_by_name(tmp_path: Path) -> None:
    store = WorkflowStore(tmp_path / "w.db")
    store.save(_workflow(name="zeta", wid="wf-zzzz0001"))
    store.save(_workflow(name="alpha", wid="wf-aaaa0001"))
    assert [w.name for w in store.list()] == ["alpha", "zeta"]
    store.close()


def test_runs_newest_first_with_paging(tmp_path: Path) -> None:
    store = WorkflowStore(tmp_path / "w.db")
    store.save(_workflow())
    for n in range(1, 6):
        store.save_run(_run("wf-test0001", f"wfr-0000000{n}", n, f"2026-09-09T0{n}:00:00Z"))
    assert store.run_count("wf-test0001") == 5
    page = store.list_runs("wf-test0001", limit=2, offset=0)
    assert [r.n for r in page] == [5, 4]
    assert [r.n for r in store.list_runs("wf-test0001", limit=2, offset=2)] == [3, 2]
    assert store.last_run("wf-test0001") is not None
    assert store.last_run("wf-test0001").n == 5  # type: ignore[union-attr]
    store.close()


def test_last_run_trigger_filter(tmp_path: Path) -> None:
    store = WorkflowStore(tmp_path / "w.db")
    store.save(_workflow())
    manual = _run("wf-test0001", "wfr-00000001", 1, "2026-09-09T01:00:00Z")
    cron = WorkflowRun(
        id="wfr-00000002",
        workflow_id="wf-test0001",
        n=2,
        trigger=Trigger.cron,
        schedule_id="sch-abc",
        spec=_workflow(),
        status=RunStatus.running,
        started_at="2026-09-09T02:00:00Z",
    )
    store.save_run(manual)
    store.save_run(cron)
    assert store.last_run("wf-test0001", Trigger.manual).id == manual.id  # type: ignore[union-attr]
    assert len(store.list_runs(schedule_id="sch-abc")) == 1
    store.close()


def test_step_run_updates_and_finish(tmp_path: Path) -> None:
    store = WorkflowStore(tmp_path / "w.db")
    store.save(_workflow())
    run = _run("wf-test0001", "wfr-00000001", 1, "2026-09-09T01:00:00Z")
    store.save_run(run)
    store.save_step_runs(
        [
            StepRun(
                run_id=run.id,
                step_name="collect",
                stage_index=0,
                task_id="t1",
                task_status="open",
                updated_at="2026-09-09T01:00:00Z",
            )
        ]
    )
    assert store.update_step_status(run.id, "collect", "closed", "2026-09-09T02:00:00Z")
    assert store.step_runs(run.id)[0].task_status == "closed"
    assert not store.update_step_status(run.id, "ghost", "closed", "2026-09-09T02:00:00Z")
    assert store.finish_run(run.id, RunStatus.succeeded, "", "2026-09-09T03:00:00Z")
    finished = store.get_run(run.id)
    assert finished is not None and finished.status is RunStatus.succeeded
    assert finished.finished_at == "2026-09-09T03:00:00Z"
    store.close()


def test_migration_from_empty_file(tmp_path: Path) -> None:
    db = tmp_path / "w.db"
    db.touch()
    store = WorkflowStore(db)
    assert store.schema_version() == SCHEMA_VERSION
    store.save(_workflow())
    assert store.get("wf-test0001") == _workflow()
    tables = {
        row[0]
        for row in sqlite3.connect(db).execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert {"workflows", "workflow_runs", "workflow_run_steps"} <= tables
    store.close()
