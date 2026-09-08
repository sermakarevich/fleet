"""Tests for `state.attempt_summary.write_summary`: the deterministic,
no-LLM SUMMARY.md rendered from one attempt's events/launch.json/attempts row.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from fleet.state.attempt_summary import write_summary
from tests.helpers.task_dir import make_attempt, make_task_dir


def _write_launch(attempt_dir: Path, mode: str = "fresh", pack_bytes: int = 0) -> None:
    (attempt_dir / "launch.json").write_text(
        json.dumps({"mode": mode, "pack_bytes": pack_bytes, "kind": "work"}), encoding="utf-8"
    )


def _write_events(attempt_dir: Path, rows: list[dict]) -> None:
    with (attempt_dir / "events.jsonl").open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


def test_write_summary_creates_file_and_returns_path(tmp_path: Path) -> None:
    task_dir = make_task_dir(tmp_path, "t-1")
    attempt_dir = make_attempt(
        task_dir, 1, outcome="done", reason="finished", exit_code=0, ended_at="2026-01-01T00:05:00+00:00"
    )
    _write_launch(attempt_dir)

    out_path = write_summary(task_dir, 1, workdir=None)

    assert out_path == attempt_dir / "SUMMARY.md"
    assert out_path.exists()
    text = out_path.read_text(encoding="utf-8")
    assert "Attempt 1 summary" in text
    assert "outcome: done (finished)" in text


def test_summary_reports_launch_mode_and_coder_model(tmp_path: Path) -> None:
    task_dir = make_task_dir(tmp_path, "t-2")
    attempt_dir = make_attempt(
        task_dir, 1, coder="claude", model="sonnet", outcome="partial", reason="next_step: x"
    )
    _write_launch(attempt_dir, mode="continue", pack_bytes=123)

    write_summary(task_dir, 1, workdir=None)
    text = (attempt_dir / "SUMMARY.md").read_text(encoding="utf-8")

    assert "launch mode: continue" in text
    assert "claude/sonnet" in text


def test_summary_includes_files_touched_and_tool_counts(tmp_path: Path) -> None:
    task_dir = make_task_dir(tmp_path, "t-3")
    attempt_dir = make_attempt(task_dir, 1, outcome="done", reason="ok")
    _write_launch(attempt_dir)
    _write_events(
        attempt_dir,
        [
            {
                "ts": "2026-01-01T00:00:00Z",
                "kind": "tool_use",
                "tool_name": "Read",
                "raw": {"part": {"type": "tool", "state": {"input": {"path": "/x.py"}}}},
            },
            {
                "ts": "2026-01-01T00:00:01Z",
                "kind": "tool_use",
                "tool_name": "Edit",
                "raw": {"part": {"type": "tool", "state": {"input": {"path": "/x.py"}}}},
            },
        ],
    )

    write_summary(task_dir, 1, workdir=None)
    text = (attempt_dir / "SUMMARY.md").read_text(encoding="utf-8")

    assert "Files touched" in text
    assert "Tool calls" in text


def test_summary_includes_last_error_and_stderr_tail(tmp_path: Path) -> None:
    task_dir = make_task_dir(tmp_path, "t-4")
    attempt_dir = make_attempt(task_dir, 1, outcome="failure", reason="crash")
    _write_launch(attempt_dir)
    _write_events(
        attempt_dir,
        [
            {"ts": "2026-01-01T00:00:00Z", "kind": "error", "raw": {"message": "boom"}},
        ],
    )
    (attempt_dir / "log.stderr").write_bytes(b"line1\nline2\nline3\n")

    write_summary(task_dir, 1, workdir=None)
    text = (attempt_dir / "SUMMARY.md").read_text(encoding="utf-8")

    assert "Last error event" in text
    assert "boom" in text
    assert "line1" in text and "line3" in text


def test_summary_includes_last_assistant_texts(tmp_path: Path) -> None:
    task_dir = make_task_dir(tmp_path, "t-5")
    attempt_dir = make_attempt(task_dir, 1, outcome="done", reason="ok")
    _write_launch(attempt_dir)
    _write_events(
        attempt_dir,
        [
            {
                "ts": "2026-01-01T00:00:00Z",
                "kind": "assistant_text",
                "raw": {"text": "hello there"},
            },
        ],
    )

    write_summary(task_dir, 1, workdir=None)
    text = (attempt_dir / "SUMMARY.md").read_text(encoding="utf-8")

    assert "assistant_text events" in text
    assert "hello there" in text


def test_summary_includes_git_commits_when_workdir_is_a_repo(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "a@b.c"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    (repo / "f.txt").write_text("hi", encoding="utf-8")
    subprocess.run(["git", "add", "f.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "add f"], cwd=repo, check=True)

    task_dir = make_task_dir(tmp_path, "t-6")
    attempt_dir = make_attempt(
        task_dir,
        1,
        outcome="done",
        reason="ok",
        started_at="2000-01-01T00:00:00+00:00",
        ended_at="2035-01-01T00:00:00+00:00",
    )
    _write_launch(attempt_dir)

    write_summary(task_dir, 1, workdir=repo)
    text = (attempt_dir / "SUMMARY.md").read_text(encoding="utf-8")

    assert "add f" in text


def test_summary_handles_no_git_repo_gracefully(tmp_path: Path) -> None:
    not_a_repo = tmp_path / "plain"
    not_a_repo.mkdir()
    task_dir = make_task_dir(tmp_path, "t-7")
    attempt_dir = make_attempt(task_dir, 1, outcome="done", reason="ok")
    _write_launch(attempt_dir)

    write_summary(task_dir, 1, workdir=not_a_repo)
    text = (attempt_dir / "SUMMARY.md").read_text(encoding="utf-8")

    assert "clean or not a git repo" in text or "(none)" in text


def test_summary_hard_capped_at_4096_chars(tmp_path: Path) -> None:
    task_dir = make_task_dir(tmp_path, "t-8")
    attempt_dir = make_attempt(task_dir, 1, outcome="done", reason="ok")
    _write_launch(attempt_dir)
    # Lots of files touched and long assistant texts to try to blow past the cap.
    events = []
    for i in range(200):
        events.append(
            {
                "ts": "2026-01-01T00:00:00Z",
                "kind": "tool_use",
                "tool_name": "Read",
                "raw": {
                    "part": {
                        "type": "tool",
                        "state": {"input": {"path": f"/file-{i}-with-a-long-name.py"}},
                    }
                },
            }
        )
    for i in range(20):
        events.append(
            {
                "ts": "2026-01-01T00:00:01Z",
                "kind": "assistant_text",
                "raw": {"text": "x" * 500 + str(i)},
            }
        )
    _write_events(attempt_dir, events)

    write_summary(task_dir, 1, workdir=None)
    text = (attempt_dir / "SUMMARY.md").read_text(encoding="utf-8")

    assert len(text) <= 4096


def test_write_summary_creates_missing_attempt_dir(tmp_path: Path) -> None:
    """write_summary is defensive: it mkdirs the attempt dir if reap.py calls
    it before anything else has created it."""
    task_dir = make_task_dir(tmp_path, "t-9")
    (task_dir / "attempts.jsonl").write_text(
        json.dumps({"event": "start", "n": 1, "ts": "2026-01-01T00:00:00+00:00",
                     "coder": "claude", "model": "sonnet", "worker": "task.fresh"}) + "\n",
        encoding="utf-8",
    )

    out_path = write_summary(task_dir, 1, workdir=None)

    assert out_path.exists()
