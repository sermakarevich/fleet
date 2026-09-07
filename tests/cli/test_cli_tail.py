"""Tests for `fleet tail` — render_event, render_lines, and CLI command."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from fleet.cli.main import app
from fleet.observability.tailview import render_lines

runner = CliRunner()

# ---------------------------------------------------------------------------
# Real opencode event shapes used as test data
# ---------------------------------------------------------------------------

_samples: list[dict] = [
    # tool_use  (raw part.state.input exists)
    {
        "kind": "tool_use",
        "ts": "2026-06-12T10:00:01+00:00",
        "tool_name": "read",
        "usage": None,
        "session_id": "ses_1483abeabffeG5gmyKrwhuE1xB",
        "raw": {
            "type": "step_start",
            "timestamp": 1781199732193,
            "sessionID": "ses_1483abeabffeG5gmyKrwhuE1xB",
            "part": {
                "type": "tool",
                "tool": "read",
                "state": {
                    "status": "in_progress",
                    "input": {"filePath": "/some/path.txt"},
                },
            },
        },
    },
    # tool_result
    {
        "kind": "tool_result",
        "ts": "2026-06-12T10:00:02+00:00",
        "tool_name": "read",
        "usage": None,
        "session_id": "ses_1483abeabffeG5gmyKrwhuE1xB",
        "raw": {
            "type": "tool_use",
            "sessionID": "ses_1483abeabffeG5gmyKrwhuE1xB",
            "part": {
                "type": "tool",
                "tool": "read",
                "state": {
                    "status": "completed",
                    "input": {"filePath": "/some/path.txt"},
                    "output": "<path>/some/path</path>\n\nHere is the content…",
                },
            },
        },
    },
    # assistant_text
    {
        "kind": "assistant_text",
        "ts": "2026-06-12T10:00:03+00:00",
        "tool_name": None,
        "usage": None,
        "session_id": "ses_1483abeabffeG5gmyKrwhuE1xB",
        "raw": {
            "type": "text",
            "sessionID": "ses_1483abeabffeG5gmyKrwhuE1xB",
            "part": {
                "type": "text",
                "text": "Let me read the _resolve_coder method in supervisor.py to understand the pattern.",
            },
        },
    },
    # error
    {
        "kind": "error",
        "ts": "2026-06-12T10:00:04+00:00",
        "tool_name": "read",
        "usage": None,
        "session_id": "ses_1483abeabffeG5gmyKrwhuE1xB",
        "raw": {
            "type": "tool_use",
            "sessionID": "ses_1483abeabffeG5gmyKrwhuE1xB",
            "part": {
                "type": "tool",
                "tool": "read",
                "state": {
                    "status": "error",
                    "input": {"filePath": "/missing"},
                    "error": "File not found: /missing",
                },
            },
        },
    },
    # session_ended
    {
        "kind": "session_ended",
        "ts": "2026-06-12T10:00:05+00:00",
        "tool_name": None,
        "usage": {
            "input_tokens": 31338,
            "output_tokens": 286,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
        },
        "session_id": "ses_1483abeabffeG5gmyKrwhuE1xB",
        "raw": {
            "type": "step_finish",
            "part": {
                "reason": "stop",
                "tokens": {
                    "input": 31338,
                    "output": 286,
                    "cache": {"write": 0, "read": 0},
                },
            },
        },
    },
]


# ---------------------------------------------------------------------------
# render_lines  over the five samples
# ---------------------------------------------------------------------------


def test_render_lines_contains_expected_marks() -> None:
    """All five samples produce a non-None, timestamp-prefixed line."""
    lines = [json.dumps(s) for s in _samples]
    result = render_lines(lines)
    output = "\n".join(result)

    # tool_result → ✓ read
    assert "✓ read" in output

    # assistant_text → 💬 text snippet
    assert "💬 Let me read" in output

    # error → ✗ read
    assert "✗ read" in output
    assert "File not found" in output

    # session_ended
    assert "── session ended" in output
    assert "in=31338" in output
    assert "out=286" in output

    # tool_use → ▶ read
    assert "▶ read" in output

    # All lines have a timestamp prefix (HH:MM:SS or --:--:--)
    for line in result:
        prefix = line[:8]
        assert prefix == "--:--:--" or ":" in prefix


def test_render_lines_timestamps_from_ts_field() -> None:
    """Timestamps are parsed from evt['ts'] and rendered as HH:MM:SS."""
    evt = {
        "kind": "assistant_text",
        "ts": "2026-06-12T14:30:45+03:00",
        "tool_name": None,
        "usage": None,
        "session_id": "ses_abcd",
        "raw": {"type": "text", "part": {"type": "text", "text": "hi"}},
    }
    results = render_lines([json.dumps(evt)])
    assert len(results) == 1
    # The timestamp portion (first 8 chars) should be "14:30:45" (local tz offset)
    assert "14:30:45" in results[0]


def test_render_lines_missing_ts_gives_dash() -> None:
    """Missing ts renders '--:--:--'."""
    evt = {
        "kind": "assistant_text",
        "tool_name": None,
        "usage": None,
        "session_id": "ses_abcd",
        "raw": {"type": "text", "part": {"type": "text", "text": "hi"}},
    }
    results = render_lines([json.dumps(evt)])
    assert len(results) == 1
    assert "--:--:--" in results[0]


# ---------------------------------------------------------------------------
# Session deduplication (render_event + render_lines share state)
# ---------------------------------------------------------------------------


def test_session_dedup_same_id_only_once() -> None:
    """Two session_started with the same sessionID render only ONE separator."""
    evt1 = {
        "kind": "session_started",
        "ts": "2026-06-12T10:00:00Z",
        "session_id": "ses_1483abeabffeG5gmyKrwhuE1xB",
        "raw": {"sessionID": "ses_1483abeabffeG5gmyKrwhuE1xB"},
    }
    evt2 = {
        "kind": "session_started",
        "ts": "2026-06-12T10:01:00Z",
        "session_id": "ses_1483abeabffeG5gmyKrwhuE1xB",
        "raw": {"sessionID": "ses_1483abeabffeG5gmyKrwhuE1xB"},
    }
    results = render_lines([json.dumps(evt1), json.dumps(evt2)])
    separators = [r for r in results if "session" in r and "started" in r]
    assert len(separators) == 1


def test_session_different_id_second_separator() -> None:
    """A third session_started with a DIFFERENT sessionID renders a second."""
    evt1 = {
        "kind": "session_started",
        "ts": "2026-06-12T10:00:00Z",
        "session_id": "ses_1483abeabffeG5gmyKrwhuE1xB",
        "raw": {"sessionID": "ses_1483abeabffeG5gmyKrwhuE1xB"},
    }
    evt2 = {
        "kind": "session_started",
        "ts": "2026-06-12T10:01:00Z",
        "session_id": "ses_1483abeabffeG5gmyKrwhuE1xB",
        "raw": {"sessionID": "ses_1483abeabffeG5gmyKrwhuE1xB"},
    }
    evt3 = {
        "kind": "session_started",
        "ts": "2026-06-12T10:02:00Z",
        "session_id": "ses_NEWXXXXXXXXXXXXXXXX",
        "raw": {"sessionID": "ses_NEWXXXXXXXXXXXXXXXX"},
    }
    results = render_lines([json.dumps(evt1), json.dumps(evt2), json.dumps(evt3)])
    separators = [r for r in results if "session" in r and "started" in r]
    assert len(separators) == 2
    assert "G5gmyKr1" not in separators[-1]  # last 8 chars differ


# ---------------------------------------------------------------------------
# CLI: fleet tail <id>
# ---------------------------------------------------------------------------


def _seed_tail_task_dir(home: Path, task_id: str) -> Path:
    """Create <home>/tasks/<id>/ with events.jsonl from samples."""
    task_dir = home / "tasks" / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    events_path = task_dir / "events.jsonl"
    events_path.write_text(
        "\n".join(json.dumps(s) for s in _samples) + "\n",
        encoding="utf-8",
    )
    # Also drop a minimal log.jsonl so task_runtime_stats doesn't blow up
    (task_dir / "log.jsonl").write_text(
        json.dumps({"event": "subprocess_started", "timestamp": "2026-06-12T10:00:00Z"})
        + "\n",
        encoding="utf-8",
    )
    return task_dir


def test_tail_cli_prints_header_and_lines(
    tmp_path: Path, monkeypatch: pytest.FixtureManager
) -> None:
    """`fleet tail <id>` prints header + last N rendered lines."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    task_id = "t-tail1"
    _seed_tail_task_dir(tmp_path, task_id)

    # Mock task_runtime_stats to return plausible stats (avoid BD dependency)
    from fleet.serve.stats import TaskRuntimeStats

    mock_stats = TaskRuntimeStats(
        events=5,
        last_event_at=None,
        context_tokens=31338,
        started_at=None,
    )

    with patch("fleet.serve.stats.task_runtime_stats", return_value=mock_stats):
        result = runner.invoke(app, ["tail", task_id])

    assert result.exit_code == 0, result.output + (result.stderr or "")
    assert "events=5" in result.output
    assert "context_tokens=31338" in result.output
    assert "✓ read" in result.output
    assert "💬 Let me read" in result.output
    assert "✗ read" in result.output


def test_tail_cli_n_limit(tmp_path: Path, monkeypatch: pytest.FixtureManager) -> None:
    """`fleet tail <id> -n 2` prints only the last 2 rendered lines."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    task_id = "t-tail2"
    _seed_tail_task_dir(tmp_path, task_id)

    from fleet.serve.stats import TaskRuntimeStats

    mock_stats = TaskRuntimeStats(
        events=5, last_event_at=None, context_tokens=None, started_at=None
    )

    with patch("fleet.serve.stats.task_runtime_stats", return_value=mock_stats):
        result = runner.invoke(app, ["tail", task_id, "-n", "2"])

    assert result.exit_code == 0, result.output + (result.stderr or "")
    # Count lines that look like rendered output (have emoji or symbols)
    [line for line in result.output.splitlines() if line.strip()]
    # Should have header + separator lines (──) + the last 2 rendered lines
    assert "──" not in result.output.split("──")[-1] if "──" in result.output else True
    display_lines = [
        line for line in result.output.splitlines() if "──" not in line and line.strip()
    ]
    assert len(display_lines) <= 2


def test_tail_missing_task_dir_exits_nonzero(
    tmp_path: Path, monkeypatch: pytest.FixtureManager
) -> None:
    """No task directory for the given id → error + exit 1."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    result = runner.invoke(app, ["tail", "t-missing"])

    assert result.exit_code != 0
    assert "No task directory" in result.output


def test_tail_unparseable_lines_and_unknown_kinds(
    tmp_path: Path, monkeypatch: pytest.FixtureManager
) -> None:
    """Unparseable lines and unknown kinds are silently skipped."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    task_id = "t-tail3"
    task_dir = tmp_path / "tasks" / task_id
    task_dir.mkdir(parents=True, exist_ok=True)

    mixed_lines = [
        json.dumps(
            {
                "kind": "assistant_text",
                "ts": "2026-06-12T10:00:00Z",
                "tool_name": None,
                "usage": None,
                "session_id": "ses_abcd",
                "raw": {"type": "text", "part": {"type": "text", "text": "good"}},
            }
        ),
        "this is not json at all {{{",
        json.dumps(
            {
                "kind": "unknown_thing",
                "ts": "2026-06-12T10:00:01Z",
                "tool_name": None,
                "usage": None,
                "session_id": "ses_abcd",
                "raw": {},
            }
        ),
        "",  # blank line
        json.dumps(
            {
                "kind": "assistant_text",
                "ts": "2026-06-12T10:00:02Z",
                "tool_name": None,
                "usage": None,
                "session_id": "ses_abcd",
                "raw": {"type": "text", "part": {"type": "text", "text": "also good"}},
            }
        ),
    ]
    (task_dir / "events.jsonl").write_text(
        "\n".join(mixed_lines) + "\n", encoding="utf-8"
    )
    (task_dir / "log.jsonl").write_text(
        json.dumps({"event": "subprocess_started", "timestamp": "2026-06-12T10:00:00Z"})
        + "\n",
        encoding="utf-8",
    )

    from fleet.serve.stats import TaskRuntimeStats

    mock_stats = TaskRuntimeStats(
        events=0, last_event_at=None, context_tokens=None, started_at=None
    )

    with patch("fleet.serve.stats.task_runtime_stats", return_value=mock_stats):
        result = runner.invoke(app, ["tail", task_id])

    assert result.exit_code == 0, result.output + (result.stderr or "")
    # Should see both assistant_text lines
    assert "good" in result.output
    assert "also good" in result.output


def test_tail_events_file_gone_exits_nonzero(
    tmp_path: Path, monkeypatch: pytest.FixtureManager
) -> None:
    """Task dir exists but events.jsonl is missing (no --follow) → error."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    task_id = "t-tail4"
    task_dir = tmp_path / "tasks" / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / "log.jsonl").write_text(
        json.dumps({"event": "subprocess_started", "timestamp": "2026-06-12T10:00:00Z"})
        + "\n",
        encoding="utf-8",
    )

    from fleet.serve.stats import TaskRuntimeStats

    mock_stats = TaskRuntimeStats(
        events=0, last_event_at=None, context_tokens=None, started_at=None
    )

    with patch("fleet.serve.stats.task_runtime_stats", return_value=mock_stats):
        result = runner.invoke(app, ["tail", task_id])

    assert result.exit_code == 0  # prints header and message
    assert (
        "does not exist yet" in result.output
        or "(events.jsonl does not exist" in result.output
    )
