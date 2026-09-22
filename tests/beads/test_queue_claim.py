"""One claim algorithm: claim_next picks, claim(id) moves (ADR 0006 bead 4)."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from fleet.beads.queue import BeadsQueue


def _ok() -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=["bd"], returncode=0, stdout="", stderr="")


@contextmanager
def _stubbed(
    queue: BeadsQueue,
    ready_rows: list[dict],
    show_bodies: dict[str, dict],
    list_rows: list[dict] | None = None,
) -> Iterator[list[list[str]]]:
    """Patch BdClient: ready/list/show read from memory, updates are recorded."""
    runs: list[list[str]] = []

    def fake_run_json(argv: list[str], **kwargs: object) -> object:
        if argv[0] == "ready":
            return ready_rows
        if argv[0] == "list":
            return list(list_rows or [])
        if argv[0] == "show":
            return dict(show_bodies.get(argv[1], {"id": argv[1], "title": argv[1]}))
        return []

    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        runs.append(argv)
        return _ok()

    with (
        patch.object(queue._client, "run_json", side_effect=fake_run_json),
        patch.object(queue._client, "run", side_effect=fake_run),
    ):
        yield runs


def test_claim_moves_open_to_in_progress_and_snapshots(tmp_path: Path) -> None:
    """claim(id) is the single place that moves open→in_progress and writes the lease."""
    q = BeadsQueue(repo_root=tmp_path)
    with _stubbed(q, [], {"t-1": {"id": "t-1", "title": "T", "status": "open"}}) as runs:
        task = q.claim("t-1", "worker-1")
    assert task.status == "in_progress"
    assert ["update", "t-1", "--claim"] in runs
    assert (tmp_path / "tasks" / "t-1" / "task.json").exists()


def test_claim_next_routes_through_claim_in_priority_order(tmp_path: Path) -> None:
    """claim_next claims the highest-priority ready task via claim(id)."""
    q = BeadsQueue(repo_root=tmp_path)
    ready = [
        {"id": "t-low", "title": "low", "priority": 2, "created_at": "2026-01-01T00:00:00Z"},
        {"id": "t-high", "title": "high", "priority": 0, "created_at": "2026-06-01T00:00:00Z"},
    ]
    bodies = {row["id"]: {**row, "status": "open"} for row in ready}
    with _stubbed(q, ready, bodies) as runs:
        task = q.claim_next("worker-1")
    assert task is not None and task.id == "t-high"
    assert task.status == "in_progress"
    assert [r for r in runs if "--claim" in r] == [["update", "t-high", "--claim"]]


def test_claim_next_predicate_filters_before_claim(tmp_path: Path) -> None:
    """The can_claim predicate skips tasks before any bd update runs."""
    q = BeadsQueue(repo_root=tmp_path)
    ready = [
        {
            "id": "t-claude",
            "title": "c",
            "priority": 1,
            "created_at": "2026-01-01T00:00:00Z",
            "metadata": {"fleet_coder": "claude"},
        },
        {
            "id": "t-codex",
            "title": "x",
            "priority": 1,
            "created_at": "2026-01-02T00:00:00Z",
            "metadata": {"fleet_coder": "codex"},
        },
    ]
    bodies = {row["id"]: {**row, "status": "open"} for row in ready}
    with _stubbed(q, ready, bodies) as runs:
        task = q.claim_next("worker-1", can_claim=lambda coder: coder == "codex")
    assert task is not None and task.id == "t-codex"
    assert [r for r in runs if "--claim" in r] == [["update", "t-codex", "--claim"]]


def test_claim_next_predicate_rejecting_all_claims_nothing(tmp_path: Path) -> None:
    """When the predicate rejects everything, no bd update runs and None returns."""
    q = BeadsQueue(repo_root=tmp_path)
    ready = [{"id": "t-1", "title": "T", "priority": 1, "created_at": "2026-01-01T00:00:00Z"}]
    with _stubbed(q, ready, {"t-1": {**ready[0], "status": "open"}}) as runs:
        assert q.claim_next("worker-1", can_claim=lambda coder: False) is None
    assert [r for r in runs if "--claim" in r] == []


def test_claim_next_skips_retry_wait(tmp_path: Path) -> None:
    """A task inside its release retry delay is skipped without a bd update."""
    q = BeadsQueue(repo_root=tmp_path)
    ready = [{"id": "t-1", "title": "T", "priority": 1, "created_at": "2026-01-01T00:00:00Z"}]
    with _stubbed(q, ready, {"t-1": {**ready[0], "status": "open"}}) as runs:
        q.release("t-1", reason="flaky", wait_sec=3600)
        assert q.claim_next("worker-1") is None
    assert [r for r in runs if "--claim" in r] == []


def _unfinished_spawn(task_dir: Path) -> None:
    """Journals that say: two children planned, one created — spawn unfinished."""
    artifacts = task_dir / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    plan = {"tasks": [{"key": "a"}, {"key": "b"}]}
    (artifacts / "tasks.json").write_text(json.dumps(plan), encoding="utf-8")
    (artifacts / "children.json").write_text(json.dumps({"a": "t-a"}), encoding="utf-8")


def _epic_row() -> dict:
    return {
        "id": "t-epic",
        "title": "epic",
        "priority": 1,
        "status": "open",
        "issue_type": "epic",
        "created_at": "2026-01-02T00:00:00Z",
    }


def test_claim_next_lets_a_resumable_epic_outrank_ready_children(tmp_path: Path) -> None:
    """An epic that still owes its spawn phase competes on priority, not last.

    Drained as a second source, it waited behind every ready child, so a job
    with hundreds of ready children never created the rest of its plan.
    """
    q = BeadsQueue(repo_root=tmp_path)
    ready = [
        {"id": "t-child", "title": "child", "priority": 2, "created_at": "2026-01-01T00:00:00Z"}
    ]
    epic = _epic_row()
    _unfinished_spawn(q._store.task_dir("t-epic"))
    bodies = {"t-child": {**ready[0], "status": "open"}, "t-epic": epic}
    with (
        _stubbed(q, ready, bodies, list_rows=[epic]) as runs,
        patch("fleet.beads.queue.children_of", return_value=[]),
    ):
        task = q.claim_next("worker-1")
    assert task is not None and task.id == "t-epic"
    assert [r for r in runs if "--claim" in r] == [["update", "t-epic", "--claim"]]


def test_claim_next_claims_an_epic_listed_by_both_sources_once(tmp_path: Path) -> None:
    """A row in `bd ready` and in the epic list is one candidate, not two."""
    q = BeadsQueue(repo_root=tmp_path)
    epic = _epic_row()
    _unfinished_spawn(q._store.task_dir("t-epic"))
    with (
        _stubbed(q, [epic], {"t-epic": epic}, list_rows=[epic]) as runs,
        patch("fleet.beads.queue.children_of", return_value=[]),
    ):
        assert q._claim_candidates() == [epic]
        task = q.claim_next("worker-1")
    assert task is not None and task.id == "t-epic"
    assert [r for r in runs if "--claim" in r] == [["update", "t-epic", "--claim"]]
