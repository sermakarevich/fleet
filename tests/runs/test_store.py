"""Tests for fleet.runs.store."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from fleet.runs.store import (
    FINISHED,
    Run,
    RunStatus,
    RunStore,
    StepRun,
    StepStatus,
    runs_db_path,
)


def _run(
    run_id: str,
    flow: str = "autocode",
    status: RunStatus = RunStatus.running,
    started: str = "2026-09-27T10:00:00+00:00",
    start_key: str | None = None,
) -> Run:
    """One run row with distinct defaults per id."""
    return Run(
        id=run_id,
        flow=flow,
        status=status,
        inputs={"feature": run_id},
        started_at=started,
        start_key=start_key,
    )


def _step(
    run_id: str,
    step: str = "build",
    item_index: int = -1,
    status: StepStatus = StepStatus.pending,
) -> StepRun:
    """One step row with distinct defaults per step name."""
    return StepRun(run_id=run_id, step=step, item_index=item_index, status=status)


def _store(path: Path) -> RunStore:
    """A RunStore on its own database file under tmp_path."""
    return RunStore(path / "runs.db")


def test_runs_db_path_joins_filename(tmp_path: Path) -> None:
    """The database file is runs.db under the fleet home."""
    assert runs_db_path(tmp_path) == tmp_path / "runs.db"


def test_schema_version_is_one(tmp_path: Path) -> None:
    """A fresh database is stamped at schema version 1."""
    store = _store(tmp_path)
    try:
        assert store.schema_version() == 1
    finally:
        store.close()


def test_create_and_get_run_round_trip(tmp_path: Path) -> None:
    """Created runs come back with inputs, reason and start key intact."""
    store = _store(tmp_path)
    try:
        assert store.get_run("missing") is None
        wanted = Run(
            id="r1",
            flow="autocode",
            status=RunStatus.running,
            inputs={"repo": "fleet", "n": 3},
            started_at="2026-09-27T10:00:00+00:00",
            reason="",
            start_key="item-7",
        )
        store.create_run(wanted)
        assert store.get_run("r1") == wanted
    finally:
        store.close()


def test_list_runs_filters_and_orders_newest_first(tmp_path: Path) -> None:
    """list_runs filters by flow and status, newest started_at first."""
    store = _store(tmp_path)
    try:
        store.create_run(_run("old", started="2026-09-27T09:00:00+00:00"))
        store.create_run(_run("new", started="2026-09-27T11:00:00+00:00"))
        store.create_run(
            _run("done", status=RunStatus.succeeded, started="2026-09-27T12:00:00+00:00")
        )
        store.create_run(_run("other", flow="helper", started="2026-09-27T13:00:00+00:00"))
        assert [run.id for run in store.list_runs()] == ["other", "done", "new", "old"]
        assert [run.id for run in store.list_runs(flow="autocode")] == [
            "done",
            "new",
            "old",
        ]
        assert [run.id for run in store.list_runs(status=RunStatus.running)] == [
            "other",
            "new",
            "old",
        ]
        assert [run.id for run in store.list_runs(flow="autocode", limit=2)] == [
            "done",
            "new",
        ]
    finally:
        store.close()


def test_finish_run_closes_known_runs(tmp_path: Path) -> None:
    """finish_run stamps status, reason and finished_at; False when unknown."""
    store = _store(tmp_path)
    try:
        store.create_run(_run("r1"))
        assert (
            store.finish_run("missing", RunStatus.failed, "nope", "2026-09-27T12:00:00+00:00")
            is False
        )
        assert (
            store.finish_run("r1", RunStatus.succeeded, "all green", "2026-09-27T12:00:00+00:00")
            is True
        )
        finished = store.get_run("r1")
        assert finished is not None
        assert finished.status == RunStatus.succeeded
        assert finished.reason == "all green"
        assert finished.finished_at == "2026-09-27T12:00:00+00:00"
    finally:
        store.close()


def test_has_start_key_matches_flow_and_key(tmp_path: Path) -> None:
    """Seen tool item keys are found only under their own flow."""
    store = _store(tmp_path)
    try:
        assert store.has_start_key("autocode", "item-7") is False
        store.create_run(_run("r1", start_key="item-7"))
        store.create_run(_run("r2"))
        assert store.has_start_key("autocode", "item-7") is True
        assert store.has_start_key("autocode", "item-8") is False
        assert store.has_start_key("helper", "item-7") is False
    finally:
        store.close()


def test_add_and_list_step_runs_ordered(tmp_path: Path) -> None:
    """Step rows list ordered by step then item_index, with key/after kept."""
    store = _store(tmp_path)
    try:
        store.create_run(_run("r1"))
        store.add_step_runs(
            [
                StepRun(
                    run_id="r1",
                    step="build",
                    item_index=1,
                    status=StepStatus.pending,
                    key="M2",
                    after=("M1",),
                ),
                _step("r1", step="plan"),
                _step("r1", step="build", item_index=0, status=StepStatus.ready),
            ]
        )
        listed = store.step_runs("r1")
        assert [(item.step, item.item_index) for item in listed] == [
            ("build", 0),
            ("build", 1),
            ("plan", -1),
        ]
        first_item = listed[1]
        assert first_item.key == "M2"
        assert first_item.after == ("M1",)
        assert store.get_step_run("r1", "build", 1) == first_item
        assert store.get_step_run("r1", "build", 9) is None
    finally:
        store.close()


def test_add_step_runs_ignores_duplicates(tmp_path: Path) -> None:
    """Re-adding the same step rows keeps the stored rows unchanged."""
    store = _store(tmp_path)
    try:
        store.create_run(_run("r1"))
        store.add_step_runs([_step("r1", status=StepStatus.ready)])
        store.set_step_status("r1", "build", -1, StepStatus.running, "2026-09-27T10:01:00+00:00")
        store.add_step_runs([_step("r1", status=StepStatus.pending)])
        current = store.get_step_run("r1", "build", -1)
        assert current is not None
        assert current.status == StepStatus.running
        assert len(store.step_runs("r1")) == 1
    finally:
        store.close()


def test_set_step_status_timestamp_rules(tmp_path: Path) -> None:
    """running stamps started_at once; FINISHED states stamp finished_at."""
    store = _store(tmp_path)
    try:
        store.create_run(_run("r1"))
        store.add_step_runs([_step("r1")])
        assert (
            store.set_step_status(
                "r1", "missing", -1, StepStatus.running, "2026-09-27T10:01:00+00:00"
            )
            is False
        )
        assert (
            store.set_step_status("r1", "build", -1, StepStatus.ready, "2026-09-27T10:01:00+00:00")
            is True
        )
        ready = store.get_step_run("r1", "build", -1)
        assert ready is not None
        assert ready.started_at is None
        assert ready.finished_at is None
        store.set_step_status("r1", "build", -1, StepStatus.running, "2026-09-27T10:02:00+00:00")
        store.set_step_status("r1", "build", -1, StepStatus.running, "2026-09-27T10:03:00+00:00")
        running = store.get_step_run("r1", "build", -1)
        assert running is not None
        assert running.started_at == "2026-09-27T10:02:00+00:00"
        assert running.finished_at is None
        store.set_step_status(
            "r1", "build", -1, StepStatus.succeeded, "2026-09-27T10:04:00+00:00", "done"
        )
        finished = store.get_step_run("r1", "build", -1)
        assert finished is not None
        assert finished.finished_at == "2026-09-27T10:04:00+00:00"
        assert finished.reason == "done"
        assert finished.started_at == "2026-09-27T10:02:00+00:00"
    finally:
        store.close()


def test_finished_covers_all_terminal_states() -> None:
    """FINISHED holds the four states that end a step run."""
    assert {
        StepStatus.succeeded,
        StepStatus.failed,
        StepStatus.skipped,
        StepStatus.cancelled,
    } == FINISHED


def test_bump_attempt_increments(tmp_path: Path) -> None:
    """bump_attempt counts 1, 2, 3 across successive retries."""
    store = _store(tmp_path)
    try:
        store.create_run(_run("r1"))
        store.add_step_runs([_step("r1")])
        assert store.bump_attempt("r1", "build", -1) == 1
        assert store.bump_attempt("r1", "build", -1) == 2
        current = store.get_step_run("r1", "build", -1)
        assert current is not None
        assert current.attempt == 2
    finally:
        store.close()


def test_ready_step_runs_oldest_run_first(tmp_path: Path) -> None:
    """ready_step_runs skips other statuses and orders by run age."""
    store = _store(tmp_path)
    try:
        store.create_run(_run("new", started="2026-09-27T11:00:00+00:00"))
        store.create_run(_run("old", started="2026-09-27T09:00:00+00:00"))
        store.add_step_runs(
            [
                _step("new", step="aaa", status=StepStatus.ready),
                _step("old", step="zzz", status=StepStatus.ready),
                _step("old", step="busy", status=StepStatus.running),
                _step("old", step="waiting", status=StepStatus.pending),
                _step("new", step="over", status=StepStatus.succeeded),
            ]
        )
        ready = store.ready_step_runs()
        assert [(item.run_id, item.step) for item in ready] == [
            ("old", "zzz"),
            ("new", "aaa"),
        ]
        assert [item.step for item in store.ready_step_runs(limit=1)] == ["zzz"]
        running = store.running_step_runs()
        assert [(item.run_id, item.step) for item in running] == [("old", "busy")]
    finally:
        store.close()


def test_deleting_run_cascades_to_step_runs(tmp_path: Path) -> None:
    """Removing a runs row deletes its step rows via ON DELETE CASCADE."""
    store = _store(tmp_path)
    try:
        store.create_run(_run("r1"))
        store.create_run(_run("r2"))
        store.add_step_runs([_step("r1"), _step("r2")])
        raw = sqlite3.connect(store.db_path)
        try:
            raw.execute("PRAGMA foreign_keys=ON")
            raw.execute("DELETE FROM runs WHERE id=?", ("r1",))
            raw.commit()
        finally:
            raw.close()
        assert store.get_run("r1") is None
        assert store.step_runs("r1") == []
        assert len(store.step_runs("r2")) == 1
    finally:
        store.close()


def test_two_instances_share_writes(tmp_path: Path) -> None:
    """Two stores on the same file see each other's runs and steps."""
    first = _store(tmp_path)
    second = RunStore(tmp_path / "runs.db")
    try:
        first.create_run(_run("r1"))
        assert second.get_run("r1") is not None
        second.add_step_runs([_step("r1", status=StepStatus.ready)])
        assert len(first.step_runs("r1")) == 1
        assert len(second.ready_step_runs()) == 1
    finally:
        first.close()
        second.close()
