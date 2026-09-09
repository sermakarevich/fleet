"""Tests for the supervisor triage loop (orchestrator/triage.py).

Uses a fake queue (records calls, no bd), real task dirs under tmp_path,
and a real QuestionStore on a tmp file.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fleet.core.config import RuntimeConfig
from fleet.core.task import Task
from fleet.core.triage_policy import (
    CLOSE,
    EDIT_RETRY,
    IGNORE_24H,
    IGNORE_FOREVER,
    RESOLVE_MERGE,
    RETRY_OPUS,
    RETRY_SAME,
    ignore_until_24h,
    repair_running_label,
)
from fleet.integrations.ask_human.store import QuestionStore
from fleet.orchestrator.triage import Triage, apply_answer, collect_candidates, triage_tick
from tests.conftest import FakeQueue as SharedFakeQueue
from tests.conftest import make_supervisor


class FakeQueue:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.blocked: list[Task] = []
        self.descriptions: dict[str, str] = {}

    def list_blocked(self, limit: int = 100) -> list[Task]:
        return self.blocked[:limit]

    def release(self, task_id: str, reason: str = "", wait_sec: int = 0) -> None:
        self.calls.append(("release", task_id, reason))

    def set_blocked(self, task_id: str, reason: str) -> None:
        self.calls.append(("set_blocked", task_id, reason))

    def close(self, task_id: str, reason: str = "completed") -> None:
        self.calls.append(("close", task_id, reason))

    def comment(self, task_id: str, body: str) -> None:
        self.calls.append(("comment", task_id, body))

    def set_overrides(self, task_id, coder=None, model=None, **kw) -> None:
        self.calls.append(("set_overrides", task_id, coder, model))

    def set_bd_fields(self, task_id: str, body: dict) -> None:
        self.calls.append(("set_bd_fields", task_id, dict(body)))
        if "description" in body:
            self.descriptions[task_id] = body["description"]

    def set_ignore(self, task_id: str, ignore_until: str) -> None:
        self.calls.append(("set_ignore", task_id, ignore_until))

    def clear_ignore(self, task_id: str) -> None:
        self.calls.append(("clear_ignore", task_id))


def _task(root: Path, task_id: str, **meta) -> Path:
    d = root / "tasks" / task_id
    d.mkdir(parents=True, exist_ok=True)
    base = {"id": task_id, "title": f"Title {task_id}", "status": "blocked"}
    base.update(meta)
    (d / "task.json").write_text(json.dumps(base), encoding="utf-8")
    return d


def _bead(task_id: str) -> Task:
    return Task(id=task_id, title=f"Title {task_id}", description=None, status="blocked")


def _store(tmp_path: Path) -> QuestionStore:
    return QuestionStore(tmp_path / "triage.db")


# --- candidate selection ----------------------------------------------------


def test_candidates_only_fleet_blocked(tmp_path: Path):
    q = FakeQueue()
    q.blocked = [_bead("fleet-1"), _bead("human-1"), _bead("no-dir")]
    _task(
        tmp_path,
        "fleet-1",
        blocked_reason="retry limit exhausted",
        blocked_at="2026-09-01T00:00:00+00:00",
    )
    _task(tmp_path, "human-1")  # human-blocked: no blocked_reason
    s = _store(tmp_path)
    cands = collect_candidates(q, tmp_path, s)
    assert [c["id"] for c in cands] == ["fleet-1"]


def test_candidates_skip_ignored_and_pending(tmp_path: Path):
    q = FakeQueue()
    q.blocked = [_bead("ign"), _bead("pend"), _bead("ok")]
    future = (datetime.now(tz=UTC) + timedelta(hours=1)).isoformat()
    _task(
        tmp_path,
        "ign",
        blocked_reason="r",
        blocked_at="2026-09-01T00:00:00+00:00",
        ignore_until=future,
    )
    _task(
        tmp_path,
        "pend",
        blocked_reason="r",
        blocked_at="2026-09-01T00:00:00+00:00",
    )
    _task(
        tmp_path,
        "ok",
        blocked_reason="r",
        blocked_at="2026-09-01T00:00:00+00:00",
    )
    s = _store(tmp_path)
    s.ask("q?", ["a"], task_id="pend", context="2026-09-01T00:00:00+00:00")
    cands = collect_candidates(q, tmp_path, s)
    assert [c["id"] for c in cands] == ["ok"]


def test_reblock_new_blocked_at_gets_fresh_question(tmp_path: Path):
    q = FakeQueue()
    q.blocked = [_bead("t")]
    _task(tmp_path, "t", blocked_reason="r", blocked_at="new-ts")
    s = _store(tmp_path)
    s.ask("old?", ["a"], task_id="t", context="old-ts")
    assert [c["id"] for c in collect_candidates(q, tmp_path, s)] == ["t"]


# --- tick: ask + digest -----------------------------------------------------


def _tick(queue: FakeQueue, root: Path, store: QuestionStore) -> dict:
    """Run one triage pass against the fake queue; return its summary."""
    sup = make_supervisor(root, queue=queue, services=[], checks=[])  # type: ignore[arg-type]
    return triage_tick(sup.state, store)


def test_tick_asks_per_task_and_digest(tmp_path: Path):
    q = FakeQueue()
    ids = [f"t-{i}" for i in range(7)]
    q.blocked = [_bead(i) for i in ids]
    for i in ids:
        _task(tmp_path, i, blocked_reason="r", blocked_at="ts")
    s = _store(tmp_path)
    summary = _tick(q, tmp_path, s)
    assert summary["candidates"] == 7
    assert summary["asked"] == 6  # 5 per-task + 1 digest
    per_task = [row for row in s.list_pending(100) if row["task_id"] is not None]
    digests = [row for row in s.list_pending(100) if row["task_id"] is None]
    assert len(per_task) == 5
    assert len(digests) == 1
    assert "t-5" in digests[0]["context"] and "t-6" in digests[0]["context"]


def test_tick_no_candidates_asks_nothing(tmp_path: Path):
    s = _store(tmp_path)
    summary = _tick(FakeQueue(), tmp_path, s)
    assert summary == {"applied": 0, "asked": 0, "candidates": 0}


# --- apply ------------------------------------------------------------------


def _answered(task_id, answer, context="ts", note=None, digest=False):
    return {
        "id": "q1",
        "task_id": None if digest else task_id,
        "context": context,
        "answer": answer,
        "note": note,
        "status": "answered",
    }


def test_apply_retry_same(tmp_path: Path):
    q = FakeQueue()
    _task(tmp_path, "t", blocked_reason="r", blocked_at="ts")
    assert apply_answer(q, tmp_path, _answered("t", RETRY_SAME)) == "released"
    assert ("release", "t", "triage: retry") in q.calls


def test_apply_retry_opus_pins_override(tmp_path: Path):
    q = FakeQueue()
    _task(tmp_path, "t", blocked_reason="r", blocked_at="ts")
    assert apply_answer(q, tmp_path, _answered("t", RETRY_OPUS)) == "released-opus"
    assert ("set_overrides", "t", "claude", "opus") in q.calls
    assert any(c[0] == "release" for c in q.calls)


def test_apply_edit_appends_note_and_releases(tmp_path: Path):
    q = FakeQueue()
    _task(
        tmp_path,
        "t",
        blocked_reason="r",
        blocked_at="ts",
        description="orig desc",
    )
    assert (
        apply_answer(q, tmp_path, _answered("t", EDIT_RETRY, note="split into A/B")) == "released"
    )
    assert q.descriptions["t"] == "orig desc\n\nOperator note: split into A/B"
    assert any(c[0] == "release" for c in q.calls)


def test_apply_close_uses_note_as_reason(tmp_path: Path):
    q = FakeQueue()
    _task(tmp_path, "t", blocked_reason="r", blocked_at="ts")
    assert apply_answer(q, tmp_path, _answered("t", CLOSE, note="obsolete")) == "closed"
    assert ("close", "t", "won't do: obsolete") in q.calls


def test_apply_close_without_note(tmp_path: Path):
    q = FakeQueue()
    _task(tmp_path, "t", blocked_reason="r", blocked_at="ts")
    apply_answer(q, tmp_path, _answered("t", CLOSE))
    assert ("close", "t", "won't do (triage)") in q.calls


def test_apply_ignore_options(tmp_path: Path):
    q = FakeQueue()
    _task(tmp_path, "t", blocked_reason="r", blocked_at="ts")
    assert apply_answer(q, tmp_path, _answered("t", IGNORE_24H)) == "ignored"
    kind, _, until = q.calls[-1]
    assert kind == "set_ignore"
    assert datetime.fromisoformat(until) > datetime.now(tz=UTC)
    assert apply_answer(q, tmp_path, _answered("t", IGNORE_FOREVER)) == "ignored"
    assert q.calls[-1] == ("set_ignore", "t", "forever")


def test_note_overrides_option(tmp_path: Path):
    """A note with 'retry same' is still appended to the description."""
    q = FakeQueue()
    _task(tmp_path, "t", blocked_reason="r", blocked_at="ts", description="d")
    assert apply_answer(q, tmp_path, _answered("t", RETRY_SAME, note="try opus?")) == "released"
    assert q.descriptions["t"] == "d\n\nOperator note: try opus?"


def test_note_alone_treated_as_edit_and_retry(tmp_path: Path):
    q = FakeQueue()
    _task(tmp_path, "t", blocked_reason="r", blocked_at="ts", description="d")
    assert apply_answer(q, tmp_path, _answered("t", None, note="just do X")) == "released"
    assert q.descriptions["t"] == "d\n\nOperator note: just do X"


def test_stale_answer_skipped(tmp_path: Path):
    """An answer for an older blocked_at (task already moved on) is a no-op."""
    q = FakeQueue()
    _task(tmp_path, "t", blocked_reason="r", blocked_at="new-ts")
    assert apply_answer(q, tmp_path, _answered("t", RETRY_SAME, context="old-ts")) == "skipped"
    assert q.calls == []
    _task(tmp_path, "t2", blocked_reason="r", blocked_at="ts", status="open")
    assert apply_answer(q, tmp_path, _answered("t2", RETRY_SAME)) == "skipped"
    assert q.calls == []


def test_ignore_honoured_after_apply(tmp_path: Path):
    """Once ignored, the task is no longer a candidate."""

    q = FakeQueue()
    q.blocked = [_bead("t")]
    d = _task(tmp_path, "t", blocked_reason="r", blocked_at="ts")
    s = _store(tmp_path)
    assert apply_answer(q, tmp_path, _answered("t", IGNORE_FOREVER)) == "ignored"
    assert q.calls[-1] == ("set_ignore", "t", "forever")
    # Simulate the real queue's persistence (FakeQueue only records calls):
    meta = json.loads((d / "task.json").read_text())
    meta["ignore_until"] = ignore_until_24h()
    meta["ignore_until"] = ignore_until_24h()
    (d / "task.json").write_text(json.dumps(meta), encoding="utf-8")
    assert collect_candidates(q, tmp_path, s) == []


def test_digest_ignore_all(tmp_path: Path):
    q = FakeQueue()
    _task(tmp_path, "a", blocked_reason="r", blocked_at="ts")
    _task(tmp_path, "b", blocked_reason="r", blocked_at="ts")
    question = _answered(None, "ignore all 24h", context="digest:a,b", digest=True)
    assert apply_answer(q, tmp_path, question) == "ignored-all"
    assert q.calls[0][0] == "set_ignore" and q.calls[0][1] == "a"
    assert q.calls[1][0] == "set_ignore" and q.calls[1][1] == "b"


def test_digest_leave_for_later_is_noop(tmp_path: Path):
    q = FakeQueue()
    question = _answered(None, "leave for later", context="digest:a", digest=True)
    assert apply_answer(q, tmp_path, question) == "skipped"
    assert q.calls == []


def test_tick_applies_answered_end_to_end(tmp_path: Path):
    q = FakeQueue()
    q.blocked = [_bead("t")]
    _task(tmp_path, "t", blocked_reason="r", blocked_at="ts")
    s = _store(tmp_path)
    qid = s.ask("fix?", [RETRY_SAME, CLOSE], task_id="t", context="ts")
    s.answer(qid, RETRY_SAME, answered_by="op")
    summary = _tick(q, tmp_path, s)
    assert summary["applied"] == 1
    assert any(c[0] == "release" for c in q.calls)


def test_triage_interval_zero_never_ticks(tmp_path: Path):
    """With triage_interval_minutes=0 the service tick returns before asking."""

    q = FakeQueue()
    q.blocked = [_bead("t")]
    _task(tmp_path, "t", blocked_reason="r", blocked_at="ts")
    store = _store(tmp_path)
    sup = make_supervisor(
        tmp_path,
        queue=q,  # type: ignore[arg-type]
        config=RuntimeConfig(triage_interval_minutes=0),
        services=[],
        checks=[],
    )
    asyncio.run(Triage(store=store).tick(sup.state))
    assert store.list_pending(100) == []
    assert q.calls == []


# --- merge-conflict repair ----------------------------------------------------

_CONFLICT_REASON = "merge conflict into main; resolve on branch fleet/orig then close"


def _conflict_meta(**overrides):
    meta = {
        "id": "orig",
        "title": "Original work",
        "status": "blocked",
        "blocked_reason": _CONFLICT_REASON,
        "blocked_at": "ts",
        "coder": "opencode",
        "model": "qwen",
        "merge_conflict": {
            "repo_root": "/repo/root",
            "base_ref": "main",
            "branch": "fleet/orig",
            "files": ["tracked.txt"],
        },
    }
    meta.update(overrides)
    return meta


def _conflict_task_file(root: Path, **overrides) -> Path:
    d = root / "tasks" / "orig"
    d.mkdir(parents=True, exist_ok=True)
    (d / "task.json").write_text(json.dumps(_conflict_meta(**overrides)), encoding="utf-8")
    return d


def test_apply_resolve_merge_spawns_one_repair_bead(tmp_path: Path):
    q = SharedFakeQueue()
    _conflict_task_file(tmp_path)
    outcome = apply_answer(q, tmp_path, _answered("orig", RESOLVE_MERGE))
    assert outcome == "repair-spawned"
    assert len(q.created) == 1
    repair = q.created[0]
    assert repair["title"] == "Resolve merge conflict: Original work"
    assert repair["labels"] == ["merge-fix", "repairs:orig"]
    assert repair["cwd"] == "/repo/root"
    assert repair["coder"] == "opencode"
    assert repair["model"] == "qwen"
    assert "-l merge-fix,repairs:orig" in (repair["extra_args"] or "")
    assert '"fleet_isolation": "none"' in (repair["extra_args"] or "")
    assert q._meta[repair["id"]] == {"fleet_isolation": "none"}
    body = repair["description"] or ""
    assert "fleet/orig" in body and "main" in body and "tracked.txt" in body
    assert "fleet bd close orig" in body
    # Original stays blocked and records the repair id.
    assert q.released == [] and q.closed == []
    meta = json.loads((tmp_path / "tasks" / "orig" / "task.json").read_text())
    assert meta["status"] == "blocked"
    assert meta["repair_task_id"] == repair["id"]


def test_apply_resolve_merge_second_answer_is_noop(tmp_path: Path):
    q = SharedFakeQueue()
    _conflict_task_file(tmp_path)
    first = apply_answer(q, tmp_path, _answered("orig", RESOLVE_MERGE))
    assert first == "repair-spawned"
    repair_id = q.created[0]["id"]
    running_label = repair_running_label(repair_id)
    assert apply_answer(q, tmp_path, _answered("orig", running_label)) == "skipped"
    assert apply_answer(q, tmp_path, _answered("orig", RESOLVE_MERGE)) == "skipped"
    assert len(q.created) == 1


def test_apply_resolve_merge_appends_note(tmp_path: Path):
    q = SharedFakeQueue()
    _conflict_task_file(tmp_path)
    assert apply_answer(q, tmp_path, _answered("orig", RESOLVE_MERGE, note="keep both")) == (
        "repair-spawned"
    )
    assert "Operator note: keep both" in (q.created[0]["description"] or "")


def test_apply_resolve_merge_without_info_skips(tmp_path: Path):
    q = SharedFakeQueue()
    _task(tmp_path, "t", blocked_reason="r", blocked_at="ts")
    assert apply_answer(q, tmp_path, _answered("t", RESOLVE_MERGE)) == "skipped"
    assert q.created == []


def test_apply_resolve_merge_respawns_after_repair_closed(tmp_path: Path):
    q = SharedFakeQueue()
    _conflict_task_file(tmp_path)
    assert apply_answer(q, tmp_path, _answered("orig", RESOLVE_MERGE)) == "repair-spawned"
    old_id = q.created[0]["id"]
    q.close(old_id, "done")
    assert apply_answer(q, tmp_path, _answered("orig", RESOLVE_MERGE)) == "repair-spawned"
    assert len(q.created) == 2
    meta = json.loads((tmp_path / "tasks" / "orig" / "task.json").read_text())
    assert meta["repair_task_id"] == q.created[1]["id"]


def test_tick_asks_merge_conflict_proposal(tmp_path: Path):
    q = SharedFakeQueue()
    orig = _conflict_meta()
    bead = Task(id="orig", title="Original work", description=None, status="blocked")
    q._tasks["orig"] = bead
    d = tmp_path / "tasks" / "orig"
    d.mkdir(parents=True, exist_ok=True)
    (d / "task.json").write_text(json.dumps(orig), encoding="utf-8")
    s = _store(tmp_path)
    summary = _tick(q, tmp_path, s)
    assert summary["candidates"] == 1
    pending = [row for row in s.list_pending(100) if row["task_id"] == "orig"]
    assert len(pending) == 1
    assert pending[0]["options"][0] == RESOLVE_MERGE
    assert "repair worker" in pending[0]["prompt"]
