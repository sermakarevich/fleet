"""Tests for the attempt journal (unit under test: state/attempts.py)."""

import json
from pathlib import Path

from fleet.state import attempts
from fleet.state.attempts import (
    latest_attempt_dir,
    load_attempts,
    record_end,
    record_start,
    record_unblock,
    set_worker,
)


def test_set_worker_tags_start_line(tmp_path: Path) -> None:
    task_dir = tmp_path / "tasks" / "t-001"
    n = record_start(task_dir, coder="claude", model="sonnet")
    assert set_worker(task_dir, n, "observer") is True
    items = attempts.load_attempts(task_dir)
    assert items[0]["worker"] == "observer"


def test_set_worker_missing_file_returns_false(tmp_path: Path) -> None:
    assert set_worker(tmp_path / "nope", 1, "observer") is False


def test_start_end_round_trip(tmp_path: Path) -> None:
    task_dir = tmp_path / "tasks" / "t-001"
    n = attempts.record_start(task_dir, coder="claude", model="sonnet")
    assert n == 1
    attempts.record_end(task_dir, outcome="failure", exit_code=1, reason="rc=1", action="released")
    items = attempts.load_attempts(task_dir)
    assert len(items) == 1
    item = items[0]
    assert item["n"] == 1
    assert item["coder"] == "claude"
    assert item["model"] == "sonnet"
    assert item["outcome"] == "failure"
    assert item["exit_code"] == 1
    assert item["reason"] == "rc=1"
    assert item["action"] == "released"
    assert item["started_at"] is not None
    assert item["ended_at"] is not None


def test_restart_count(tmp_path: Path) -> None:
    task_dir = tmp_path / "tasks" / "t-001"
    assert attempts.restart_count(task_dir) == 0
    attempts.record_start(task_dir, coder="a", model="m")
    assert attempts.restart_count(task_dir) == 0
    attempts.record_start(task_dir, coder="a", model="m")
    assert attempts.restart_count(task_dir) == 1
    attempts.record_start(task_dir, coder="a", model="m")
    assert attempts.restart_count(task_dir) == 2


def test_malformed_line_skipped(tmp_path: Path) -> None:
    task_dir = tmp_path / "tasks" / "t-001"
    task_dir.mkdir(parents=True)
    attempts.record_start(task_dir, coder="claude", model="sonnet")
    with (task_dir / "attempts.jsonl").open("a", encoding="utf-8") as f:
        f.write("not json at all\n")
        f.write('{"event": "start"}\n')  # missing n
    items = attempts.load_attempts(task_dir)
    assert len(items) == 1
    assert items[0]["n"] == 1


def test_load_attempts_merges_and_computes_duration(tmp_path: Path) -> None:
    task_dir = tmp_path / "tasks" / "t-001"
    task_dir.mkdir(parents=True)
    lines = [
        {
            "event": "start",
            "n": 1,
            "ts": "2026-01-01T00:00:00+00:00",
            "coder": "claude",
            "model": "sonnet",
        },
        {
            "event": "end",
            "n": 1,
            "ts": "2026-01-01T00:01:40+00:00",
            "outcome": "failure",
            "exit_code": 1,
            "reason": "rc=1",
            "action": "released",
        },
        {
            "event": "start",
            "n": 2,
            "ts": "2026-01-01T00:02:00+00:00",
            "coder": "claude",
            "model": "sonnet",
        },
    ]
    with (task_dir / "attempts.jsonl").open("w", encoding="utf-8") as f:
        for obj in lines:
            f.write(json.dumps(obj) + "\n")
    items = attempts.load_attempts(task_dir)
    assert [i["n"] for i in items] == [1, 2]
    assert items[0]["duration_sec"] == 100.0
    assert items[1]["ended_at"] is None
    assert items[1]["duration_sec"] is None
    assert attempts.last_attempt(task_dir)["n"] == 2


def test_last_attempt_none_when_empty(tmp_path: Path) -> None:
    assert attempts.last_attempt(tmp_path / "tasks" / "missing") is None


def test_record_unblock_adds_row_and_keeps_numbering(tmp_path: Path) -> None:
    """An unblock row gets its own n, loads as kind "unblock"/outcome
    "unblocked", and the next start continues numbering after it."""

    n1 = record_start(tmp_path, coder="c", model="m")
    record_end(tmp_path, outcome="failure", exit_code=1, reason="boom", action="block")
    n_unblock = record_unblock(tmp_path, "looks fine")
    n2 = record_start(tmp_path, coder="c", model="m")
    assert (n1, n_unblock, n2) == (1, 2, 3)

    rows = load_attempts(tmp_path)
    assert [r["n"] for r in rows] == [1, 2, 3]
    row = rows[1]
    assert row["kind"] == "unblock"
    assert row["outcome"] == "unblocked"
    assert row["reason"] == "looks fine"
    assert row["started_at"] == row["ended_at"]


def test_latest_attempt_dir_prefers_the_running_work_attempt(tmp_path: Path) -> None:
    """A compaction row (n=3) is recorded after the work attempt (n=2) starts
    and finishes long before it; while n=2 runs, n=2 is the latest."""
    task_dir = tmp_path / "t"
    task_dir.mkdir()
    record_start(task_dir, coder="opencode", model="m")  # n=1
    record_end(task_dir, outcome="failure", exit_code=-15, reason="x", action="release")
    n_work = record_start(task_dir, coder="opencode", model="m")  # n=2, still running
    n_compact = record_start(task_dir, coder="claude", model="haiku", kind="compact")  # n=3
    record_end(
        task_dir,
        outcome="success",
        exit_code=0,
        reason="compacted",
        action="close",
        attempt_no=n_compact,
    )

    assert latest_attempt_dir(task_dir).name == str(n_work)

    record_end(
        task_dir,
        outcome="killed",
        exit_code=-15,
        reason="stalled",
        action="release",
        attempt_no=n_work,
    )
    assert latest_attempt_dir(task_dir).name == str(n_compact)
