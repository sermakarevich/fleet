"""Tests for `state.attempt_journal.AttemptJournal`, the attempts.jsonl owner."""

from __future__ import annotations

from pathlib import Path

from fleet.state.attempt_journal import AttemptJournal


def _task_dir(tmp_path: Path) -> Path:
    task_dir = tmp_path / "tasks" / "t-001"
    task_dir.mkdir(parents=True)
    return task_dir


def test_empty_journal_answers_zeros_and_none(tmp_path: Path) -> None:
    journal = AttemptJournal.load(_task_dir(tmp_path))
    assert journal.rows == []
    assert journal.starts == 0
    assert journal.max_n == 0
    assert journal.current_n == 0
    assert journal.restart_count == 0
    assert journal.last is None
    assert journal.latest_attempt_dir() is None


def test_start_end_round_trip_and_derived_counts(tmp_path: Path) -> None:
    task_dir = _task_dir(tmp_path)
    journal = AttemptJournal.load(task_dir)
    n1 = journal.append_start(coder="claude", model="sonnet")
    n2 = journal.append_start(coder="claude", model="sonnet")
    assert (n1, n2) == (1, 2)
    journal.append_end(
        outcome="failure", exit_code=1, reason="boom", action="release", attempt_no=n1
    )

    fresh = AttemptJournal.load(task_dir)
    assert fresh.starts == 2
    assert fresh.max_n == 2
    assert fresh.current_n == 2
    assert fresh.restart_count == 1
    assert len(fresh.rows) == 2
    assert fresh.rows[0]["outcome"] == "failure"
    assert fresh.rows[0]["duration_sec"] is not None
    assert fresh.last == fresh.rows[-1]


def test_end_defaults_to_current_attempt(tmp_path: Path) -> None:
    task_dir = _task_dir(tmp_path)
    journal = AttemptJournal.load(task_dir)
    journal.append_start(coder="c", model="m")
    journal.append_end(outcome="success", exit_code=0, reason="", action="close")
    assert AttemptJournal.load(task_dir).rows[0]["ended_at"] is not None


def test_unblock_gets_own_row_and_numbering(tmp_path: Path) -> None:
    task_dir = _task_dir(tmp_path)
    journal = AttemptJournal.load(task_dir)
    journal.append_start(coder="c", model="m")
    n_unblock = journal.append_unblock("looks fine")
    assert n_unblock == 2
    rows = AttemptJournal.load(task_dir).rows
    assert rows[-1]["kind"] == "unblock"
    assert rows[-1]["outcome"] == "unblocked"


def test_set_worker_tags_line_and_reports_missing(tmp_path: Path) -> None:
    task_dir = _task_dir(tmp_path)
    journal = AttemptJournal.load(task_dir)
    n = journal.append_start(coder="c", model="m")
    assert journal.set_worker(n, "observer") is True
    assert AttemptJournal.load(task_dir).rows[0]["worker"] == "observer"
    assert journal.set_worker(999, "observer") is False
    assert AttemptJournal.load(tmp_path / "nope").set_worker(1, "observer") is False


def test_latest_attempt_dir_prefers_running_work_attempt(tmp_path: Path) -> None:
    task_dir = _task_dir(tmp_path)
    journal = AttemptJournal.load(task_dir)
    journal.append_start(coder="c", model="m")
    journal.append_end(outcome="failure", exit_code=1, reason="x", action="release")
    n_work = journal.append_start(coder="c", model="m")
    n_compact = journal.append_start(coder="c", model="m", kind="compact")
    journal.append_end(
        outcome="success", exit_code=0, reason="c", action="close", attempt_no=n_compact
    )
    fresh = AttemptJournal.load(task_dir)
    assert fresh.latest_attempt_dir() is not None
    assert fresh.latest_attempt_dir().name == str(n_work)
    assert fresh.latest_attempt_dir(before_n=n_compact).name in ("1", str(n_work))
