"""Tests for `state.attempt_summary`: the derived, no-LLM per-attempt summary.

`summarize` computes an `AttemptSummary` from one attempt's run.json /
events.jsonl / attempts.jsonl row / RESULT.json snapshot; `render_markdown`
renders it (capped at ~4 KB). Nothing is ever written to disk.
"""

from __future__ import annotations

import json
from pathlib import Path

from fleet.state.attempt_summary import render_markdown, summarize
from tests.helpers.task_dir import make_attempt, make_task_dir


def _write_run(attempt_dir: Path, launch: dict | None = None) -> None:
    payload: dict = {}
    if launch is not None:
        payload["launch"] = launch
    (attempt_dir / "run.json").write_text(json.dumps(payload), encoding="utf-8")


def _write_events(attempt_dir: Path, rows: list[dict]) -> None:
    with (attempt_dir / "events.jsonl").open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


def test_summarize_reads_run_launch_and_attempt_row(tmp_path: Path) -> None:
    task_dir = make_task_dir(tmp_path, "t-1")
    attempt_dir = make_attempt(
        task_dir,
        1,
        coder="claude",
        model="sonnet",
        outcome="done",
        reason="finished",
        exit_code=0,
        ended_at="2026-01-01T00:05:00+00:00",
    )
    _write_run(attempt_dir, {"mode": "fresh", "pack_bytes": 0, "kind": "work"})

    summary = summarize(task_dir, 1)

    assert summary.n == 1
    assert summary.mode == "fresh"
    assert summary.kind == "work"
    assert summary.coder == "claude"
    assert summary.model == "sonnet"
    assert summary.outcome == "done"
    assert summary.exit_code == 0


def test_summarize_continue_mode_from_run_json(tmp_path: Path) -> None:
    task_dir = make_task_dir(tmp_path, "t-2")
    attempt_dir = make_attempt(
        task_dir, 1, coder="claude", model="sonnet", outcome="partial", reason="next_step: x"
    )
    _write_run(attempt_dir, {"mode": "continue", "pack_bytes": 123, "kind": "work"})

    summary = summarize(task_dir, 1)
    text = render_markdown(summary)

    assert summary.mode == "continue"
    assert "launch mode: continue" in text
    assert "claude/sonnet" in text


def test_summarize_includes_files_touched_and_tool_counts(tmp_path: Path) -> None:
    task_dir = make_task_dir(tmp_path, "t-3")
    attempt_dir = make_attempt(task_dir, 1, outcome="done", reason="ok")
    _write_run(attempt_dir)
    _write_events(
        attempt_dir,
        [
            {
                "ts": "2026-01-01T00:00:00Z",
                "kind": "tool_use",
                "tool_name": "Read",
                "raw": {"input": {"file_path": "/x.py"}},
            },
            {
                "ts": "2026-01-01T00:00:01Z",
                "kind": "tool_use",
                "tool_name": "Edit",
                "raw": {"input": {"file_path": "/x.py"}},
            },
        ],
    )

    summary = summarize(task_dir, 1)
    text = render_markdown(summary)

    assert summary.tool_counts == {"Read": 1, "Edit": 1}
    assert set(summary.files_touched) == {"/x.py"}
    assert "Files touched" in text
    assert "Tool calls" in text


def test_summarize_includes_last_error_and_stderr_tail(tmp_path: Path) -> None:
    task_dir = make_task_dir(tmp_path, "t-4")
    attempt_dir = make_attempt(task_dir, 1, outcome="failure", reason="crash")
    _write_run(attempt_dir)
    _write_events(
        attempt_dir,
        [
            {"ts": "2026-01-01T00:00:00Z", "kind": "error", "raw": {"message": "boom"}},
        ],
    )
    (attempt_dir / "log.stderr").write_bytes(b"line1\nline2\nline3\n")

    summary = summarize(task_dir, 1)
    text = render_markdown(summary)

    assert "Last error event" in text
    assert "boom" in text
    assert "line1" in text and "line3" in text


def test_summarize_includes_last_assistant_texts(tmp_path: Path) -> None:
    task_dir = make_task_dir(tmp_path, "t-5")
    attempt_dir = make_attempt(task_dir, 1, outcome="done", reason="ok")
    _write_run(attempt_dir)
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

    text = render_markdown(summarize(task_dir, 1))

    assert "assistant_text events" in text
    assert "hello there" in text


def test_summarize_includes_declared_result_snapshot(tmp_path: Path) -> None:
    task_dir = make_task_dir(tmp_path, "t-6")
    attempt_dir = make_attempt(task_dir, 1, outcome="done", reason="ok")
    _write_run(attempt_dir)
    (attempt_dir / "RESULT.json").write_text(
        '{"schema": 1, "status": "done", "summary": "shipped it"}', encoding="utf-8"
    )

    summary = summarize(task_dir, 1)

    assert summary.result == {"schema": 1, "status": "done", "summary": "shipped it"}
    assert "shipped it" in render_markdown(summary)


def test_summarize_counts_cli_compactions(tmp_path: Path) -> None:
    task_dir = make_task_dir(tmp_path, "t-7")
    attempt_dir = make_attempt(task_dir, 1, outcome="done", reason="ok")
    _write_run(attempt_dir)
    (attempt_dir / ".compacted").touch()

    assert summarize(task_dir, 1).cli_compactions == 1


def test_render_hard_capped_at_4096_chars(tmp_path: Path) -> None:
    task_dir = make_task_dir(tmp_path, "t-8")
    attempt_dir = make_attempt(task_dir, 1, outcome="done", reason="ok")
    _write_run(attempt_dir)
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

    text = render_markdown(summarize(task_dir, 1))

    assert len(text) <= 4096


def test_summarize_writes_nothing_to_disk(tmp_path: Path) -> None:
    """Derived summaries leave no files behind."""
    task_dir = make_task_dir(tmp_path, "t-9")
    attempt_dir = make_attempt(task_dir, 1, outcome="done", reason="ok")
    _write_run(attempt_dir)

    render_markdown(summarize(task_dir, 1))

    assert not (attempt_dir / "SUMMARY.md").exists()
    assert (attempt_dir / "run.json").exists()
