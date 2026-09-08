"""Tests for `state.run_file.RunRecord`, the run.json owner."""

from __future__ import annotations

import json
from pathlib import Path

from fleet.state.run_file import RunRecord


def _attempt_dir(tmp_path: Path) -> Path:
    attempt_dir = tmp_path / "tasks" / "t-001" / "attempts" / "1"
    attempt_dir.mkdir(parents=True)
    return attempt_dir


def test_load_returns_none_when_missing(tmp_path: Path) -> None:
    assert RunRecord.load(_attempt_dir(tmp_path)) is None


def test_merge_creates_and_preserves_other_keys(tmp_path: Path) -> None:
    attempt_dir = _attempt_dir(tmp_path)
    RunRecord.merge(attempt_dir, launch={"mode": "fresh", "pack_bytes": 0, "kind": "work"})
    RunRecord.merge(attempt_dir, pid=123, heartbeat_at="now", lease_until="later")
    raw = json.loads((attempt_dir / "run.json").read_text(encoding="utf-8"))
    assert raw["launch"]["mode"] == "fresh"
    assert raw["pid"] == 123
    record = RunRecord.load(attempt_dir)
    assert record is not None
    assert record.pid == 123
    assert record.launch == {"mode": "fresh", "pack_bytes": 0, "kind": "work"}


def test_touch_lease_refreshes_heartbeat_and_lease(tmp_path: Path) -> None:
    attempt_dir = _attempt_dir(tmp_path)
    RunRecord.merge(attempt_dir, pid=7)
    record = RunRecord.touch_lease(attempt_dir, "2030-01-01T00:00:00+00:00")
    assert record.lease_until == "2030-01-01T00:00:00+00:00"
    assert record.heartbeat_at is not None
    assert record.pid == 7


def test_record_step_appends_and_stamps_worker(tmp_path: Path) -> None:
    attempt_dir = _attempt_dir(tmp_path)
    RunRecord.record_step(attempt_dir, "task.fresh", {"name": "prepare", "status": "ok"})
    RunRecord.record_step(attempt_dir, "task.fresh", {"name": "session", "status": "ok"})
    record = RunRecord.load(attempt_dir)
    assert record is not None
    assert record.worker == "task.fresh"
    assert [s["name"] for s in record.steps] == ["prepare", "session"]


def test_extra_keys_survive_round_trip(tmp_path: Path) -> None:
    attempt_dir = _attempt_dir(tmp_path)
    (attempt_dir / "run.json").write_text(
        json.dumps({"pid": 1, "custom": {"a": [1, 2]}}), encoding="utf-8"
    )
    record = RunRecord.load(attempt_dir)
    assert record is not None
    assert record.extra == {"custom": {"a": [1, 2]}}
    assert record.to_dict()["custom"] == {"a": [1, 2]}
