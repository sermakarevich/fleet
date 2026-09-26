"""Tests for the blocked-task helper spawn service (orchestrator/helper.py).

Uses a fake queue that parses ``bd create`` extra_args like bd would
(metadata + labels, readable back via ``list_by_metadata``), real task
dirs under tmp_path, and a recording stub in place of QuestionStore.
"""

from __future__ import annotations

import dataclasses
import json
import shlex
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import structlog

from fleet.core.clock import FakeClock
from fleet.core.config import RuntimeConfig
from fleet.core.helper_report import HelperReport
from fleet.core.task import Task
from fleet.orchestrator.helper import helper_tick, progress_check
from fleet.state.task_meta import TaskMeta

BLOCKED_AT = "2026-09-01T00:00:00+00:00"


class FakeQueue:
    """Blocked beads plus created helpers; bd metadata/labels parsed from extra_args."""

    def __init__(self) -> None:
        self.tasks: dict[str, Task] = {}
        self.metadata: dict[str, dict] = {}
        self.created: list[dict] = []
        self._n = 0

    def add_blocked(self, task_id: str) -> None:
        self.tasks[task_id] = Task(
            id=task_id, title=f"Title {task_id}", description=None, status="blocked"
        )

    def get(self, task_id: str) -> Task:
        return self.tasks[task_id]

    def list_blocked(self, limit: int = 100) -> list[Task]:
        return [t for t in self.tasks.values() if t.status == "blocked"][:limit]

    def list_by_metadata(self, field: str, value: str) -> list[Task]:
        return [self.tasks[i] for i, md in self.metadata.items() if md.get(field) == value]

    def create_task(self, title, description=None, cwd=None, coder=None, model=None, **kw):
        self._n += 1
        task_id = f"helper-{self._n}"
        argv = shlex.split(kw.get("extra_args") or "")
        metadata = json.loads(argv[argv.index("--metadata") + 1])
        labels = tuple(argv[argv.index("-l") + 1].split(","))
        priority = argv[argv.index("--priority") + 1]
        task = Task(id=task_id, title=title, description=description, status="open", labels=labels)
        self.tasks[task_id] = task
        self.metadata[task_id] = metadata
        self.created.append(
            {
                "id": task_id,
                "labels": labels,
                "metadata": metadata,
                "priority": priority,
                "coder": coder,
                "model": model,
                "cwd": cwd,
                "description": description,
            }
        )
        return task

    def block(self, task_id: str) -> None:
        self.tasks[task_id] = dataclasses.replace(self.tasks[task_id], status="blocked")


class FakeStore:
    def __init__(self) -> None:
        self.asked: list[dict] = []

    def ask(self, prompt, options=None, **kw) -> str:
        self.asked.append({"prompt": prompt, "options": options, **kw})
        return f"q{len(self.asked)}"


def _task(root: Path, task_id: str, **meta) -> Path:
    d = root / "tasks" / task_id
    d.mkdir(parents=True, exist_ok=True)
    base = {"id": task_id, "title": f"Title {task_id}", "status": "blocked", "cwd": "/repo"}
    base.update(meta)
    (d / "task.json").write_text(json.dumps(base), encoding="utf-8")
    return d


def _st(tmp_path: Path, queue: FakeQueue, *, enabled: bool = True) -> SimpleNamespace:
    config = dataclasses.replace(RuntimeConfig(), helper_enabled=enabled)
    return SimpleNamespace(
        config=config,
        queue=queue,
        fleet_home=tmp_path,
        log=structlog.get_logger(),
        clock=FakeClock(start=datetime(2026, 9, 2, tzinfo=UTC)),
    )


def _meta(root: Path, task_id: str) -> dict:
    return json.loads((root / "tasks" / task_id / "task.json").read_text())


def _write_report(root: Path, task_id: str, same: str) -> None:
    d = root / "tasks" / task_id / "artifacts"
    d.mkdir(parents=True, exist_ok=True)
    (d / "HELPER_REPORT.md").write_text(
        "## Root cause\nDisk full.\n\n## Evidence\nENOSPC in log.\n\n"
        f"## Same as previous root cause\n{same}\n\n## Proposed fixes\nFree space.\n",
        encoding="utf-8",
    )


def _blocked_target(tmp_path: Path, q: FakeQueue, task_id: str = "t1", **meta) -> None:
    q.add_blocked(task_id)
    _task(tmp_path, task_id, blocked_reason="retry limit exhausted", blocked_at=BLOCKED_AT, **meta)


# --- spawning and dedup -------------------------------------------------------


def test_spawns_one_helper_with_labels_and_links_target(tmp_path: Path):
    q = FakeQueue()
    _blocked_target(tmp_path, q)
    summary = helper_tick(_st(tmp_path, q), FakeStore())
    assert summary["spawned"] == 1
    [created] = q.created
    assert set(created["labels"]) == {"helper", "helps:t1", "chain:t1"}
    assert created["priority"] == "0"
    assert created["metadata"] == {"chain_root": "t1", "helper_for": "t1", "chain_seq": 1}
    assert (created["coder"], created["model"]) == ("claude", "opus")
    assert "t1" in created["description"]
    meta = _meta(tmp_path, "t1")
    assert meta["helper_task_id"] == created["id"]
    assert meta["helper_blocked_at"] == BLOCKED_AT


def test_second_tick_dedups_live_helper_same_block(tmp_path: Path):
    q = FakeQueue()
    _blocked_target(tmp_path, q)
    st = _st(tmp_path, q)
    helper_tick(st, FakeStore())
    summary = helper_tick(st, FakeStore())
    assert summary["spawned"] == 0
    assert len(q.created) == 1


def test_reblock_while_helper_live_does_not_spawn_second(tmp_path: Path):
    q = FakeQueue()
    _blocked_target(tmp_path, q)
    st = _st(tmp_path, q)
    helper_tick(st, FakeStore())
    TaskMeta.update(tmp_path / "tasks" / "t1", blocked_at="2026-09-01T05:00:00+00:00")
    summary = helper_tick(st, FakeStore())
    assert summary["spawned"] == 0
    assert len(q.created) == 1


def test_reblock_after_helper_closed_spawns_fresh_helper(tmp_path: Path):
    q = FakeQueue()
    _blocked_target(tmp_path, q)
    st = _st(tmp_path, q)
    helper_tick(st, FakeStore())
    first = q.created[0]["id"]
    q.tasks[first] = dataclasses.replace(q.tasks[first], status="closed")
    TaskMeta.update(tmp_path / "tasks" / "t1", blocked_at="2026-09-01T05:00:00+00:00")
    helper_tick(st, FakeStore())
    assert len(q.created) == 2


def test_human_blocked_bead_skipped(tmp_path: Path):
    q = FakeQueue()
    q.add_blocked("h1")
    _task(tmp_path, "h1")
    assert helper_tick(_st(tmp_path, q), FakeStore())["spawned"] == 0
    assert q.created == []


def test_active_ignore_until_skipped(tmp_path: Path):
    q = FakeQueue()
    future = (datetime(2026, 9, 2, tzinfo=UTC) + timedelta(hours=1)).isoformat()
    _blocked_target(tmp_path, q, ignore_until=future)
    helper_tick(_st(tmp_path, q), FakeStore())
    assert q.created == []


def test_disabled_scans_nothing(tmp_path: Path):
    q = FakeQueue()
    _blocked_target(tmp_path, q)
    scanned = []
    q.list_blocked = lambda limit=100: scanned.append(limit) or []  # type: ignore[method-assign]
    store = FakeStore()
    summary = helper_tick(_st(tmp_path, q, enabled=False), store)
    assert summary["spawned"] == 0
    assert scanned == []
    assert q.created == []
    assert store.asked == []


# --- progress check and chains -----------------------------------------------


def test_progress_check():
    assert progress_check([]) is False
    assert progress_check([HelperReport(same_as_previous=True)]) is True
    assert progress_check([HelperReport(same_as_previous=False)]) is False
    assert progress_check([HelperReport(same_as_previous=None)]) is False


def test_helper_of_helper_keeps_chain_root(tmp_path: Path):
    q = FakeQueue()
    _blocked_target(tmp_path, q, "T")
    st = _st(tmp_path, q)
    helper_tick(st, FakeStore())
    h1 = q.created[0]["id"]
    # H1 wrote its report, then fleet blocked it automatically.
    _write_report(tmp_path, h1, "no, first helper")
    q.block(h1)
    TaskMeta.update(tmp_path / "tasks" / h1, blocked_reason="stalled", blocked_at=BLOCKED_AT)
    helper_tick(st, FakeStore())
    assert len(q.created) == 2
    h2 = q.created[1]
    assert f"helps:{h1}" in h2["labels"]
    assert "chain:T" in h2["labels"]
    assert f"chain:{h1}" not in h2["labels"]
    assert h2["metadata"]["chain_seq"] == 2
    assert h2["metadata"]["chain_root"] == "T"
    assert "Disk full." in h2["description"]


def test_chain_stops_when_root_cause_repeats(tmp_path: Path):
    q = FakeQueue()
    _blocked_target(tmp_path, q, "T")
    st = _st(tmp_path, q)
    helper_tick(st, FakeStore())
    h1 = q.created[0]["id"]
    _write_report(tmp_path, h1, "yes, same disk issue")
    q.block(h1)
    TaskMeta.update(tmp_path / "tasks" / h1, blocked_reason="stalled", blocked_at=BLOCKED_AT)
    store = FakeStore()
    summary = helper_tick(st, store)
    assert summary["spawned"] == 0
    assert summary["chain_stopped"] == 1
    assert len(q.created) == 1
    [asked] = store.asked
    assert asked["task_id"] == "T"
    assert asked["context"] == "chain-stopped:T"
    assert asked["agent_id"] == "helper"
    assert "Disk full." in asked["prompt"]
    assert _meta(tmp_path, "T")["chain_stopped"] is True
    helper_tick(st, store)
    assert len(store.asked) == 1
    assert len(q.created) == 1
