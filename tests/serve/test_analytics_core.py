"""Tests for ``analytics_core`` — pure unit tests (no HTTP, no app)."""

from __future__ import annotations

import json
from pathlib import Path

from fleet.serve.analytics.records import collect_records, task_record_cached


def _write_task_json(d: Path, **fields) -> dict:
    data = {
        "title": "test task",
        "coder": "test-coder",
        "model": "sonata-pro",
        "cwd": "/tmp",
        "priority": 1,
        "status": "running",
        **fields,
    }
    (d / "task.json").write_text(json.dumps(data), "utf-8")
    return data


def _write_events(d: Path, lines: list[str]) -> None:
    attempt_dir = d / "attempts" / "1"
    attempt_dir.mkdir(parents=True, exist_ok=True)
    (attempt_dir / "events.jsonl").write_text("\n".join(lines) + "\n", "utf-8")


def _event(**kw) -> str:
    return json.dumps(kw)


class TestTaskRecordFull:
    """Test 1: full task with all features."""

    def test_all_fields(self, tmp_path: Path) -> None:
        td = tmp_path / "tasks" / "task-full"
        td.mkdir(parents=True)
        _write_task_json(td, title="Full test", status="done")

        evs = [
            _event(ts="2025-01-01T10:00:00Z", kind="session_started", session_id="s1"),
            _event(ts="2025-01-01T11:00:00Z", kind="session_started", session_id="s2"),
            _event(
                ts="2025-01-01T12:00:00Z",
                kind="tool_result",
                tool_name="Read",
                usage={
                    "input_tokens": 100,
                    "output_tokens": 200,
                    "cache_creation_input_tokens": 50,
                    "cache_read_input_tokens": 10,
                },
            ),
            _event(
                ts="2025-01-02T14:00:00Z",
                kind="tool_result",
                tool_name="Edit",
                usage={
                    "input_tokens": 150,
                    "output_tokens": 300,
                    "cache_creation_input_tokens": 30,
                    "cache_read_input_tokens": 20,
                },
            ),
            _event(ts="2025-01-02T15:00:00Z", kind="error"),
            _event(ts="malformed-ts", kind="error"),  # ts not parseable but event still counts
            "THIS IS NOT JSON",  # malformed line — should be skipped
        ]
        _write_events(td, evs)

        r = task_record_cached(td)

        assert r["id"] == "task-full"
        assert r["title"] == "Full test"
        assert r["status_raw"] == "done"
        assert r["first_ts"] == "2025-01-01T10:00:00+00:00"
        assert r["last_ts"] is not None
        # malformed line is excluded from events count
        assert r["events"] == 6  # 6 valid lines (including malformed-ts one)
        assert r["steps"] == 2
        assert r["segments"] == 2  # s1, s2
        assert r["errors"] == 2
        assert r["tool_counts"] == {"Read": 1, "Edit": 1}
        assert r["output_tokens"] == 500  # 200 + 300
        assert r["input_tokens"] == 250  # 100 + 150
        assert r["cache_creation_tokens"] == 80  # 50 + 30
        assert r["cache_read_tokens"] == 30  # 10 + 20
        assert r["peak_context_tokens"] == 200
        assert r["rate_limited"] == 0
        assert r["noclose"] is False


class TestRateLimit:
    """Test 2: rate_limit_info rejected + success/release attempt history."""

    def test_rate_limit_and_noclose(self, tmp_path: Path) -> None:
        td = tmp_path / "tasks" / "task-rl"
        td.mkdir(parents=True)
        _write_task_json(td)
        # noclose is derived from attempts history: latest end is a
        # success that released (rc=0 without RESULT.json close).
        (td / "attempts.jsonl").write_text(
            "\n".join(
                [
                    json.dumps({"event": "start", "n": 1, "ts": "2025-03-05T08:00:00+00:00"}),
                    json.dumps(
                        {
                            "event": "end",
                            "n": 1,
                            "ts": "2025-03-05T08:03:00+00:00",
                            "outcome": "success",
                            "exit_code": 0,
                            "reason": "rc=0 without close",
                            "action": "release",
                        }
                    ),
                ]
            )
            + "\n",
            "utf-8",
        )

        evs = [
            _event(ts="2025-03-05T08:00:00Z", kind="rate_limit_info"),
            _event(
                ts="2025-03-05T08:01:00Z",
                kind="rate_limit_info",
                rate_info={"status": "rejected"},
            ),
            _event(
                ts="2025-03-05T08:02:00Z",
                kind="rate_limit",
                rate_info={"status": "rejected"},
            ),
        ]
        _write_events(td, evs)

        r = task_record_cached(td)
        assert r["rate_limited"] == 2
        assert len(r["rate_limit_events"]) == 2
        assert "2025-03-05T08:01:00Z" in r["rate_limit_events"]
        assert "2025-03-05T08:02:00Z" in r["rate_limit_events"]
        assert r["noclose"] is True


class TestToolUseFallback:
    """tool_counts falls back to named tool_use events (claude-style streams)."""

    def test_tool_use_counted_when_no_named_tool_result(self, tmp_path: Path) -> None:
        td = tmp_path / "tasks" / "task-tu"
        td.mkdir(parents=True)
        _write_task_json(td)
        evs = [
            _event(ts="2025-01-01T10:00:00Z", kind="tool_use", tool_name="Read"),
            _event(ts="2025-01-01T10:01:00Z", kind="tool_use", tool_name="Read"),
            _event(ts="2025-01-01T10:02:00Z", kind="tool_use", tool_name="Bash"),
            # claude tool_result events carry no name — must stay ignored
            _event(ts="2025-01-01T10:03:00Z", kind="tool_result", tool_name=None),
        ]
        _write_events(td, evs)

        r = task_record_cached(td)
        assert r["tool_counts"] == {"Read": 2, "Bash": 1}

    def test_named_tool_result_wins_over_tool_use(self, tmp_path: Path) -> None:
        """opencode emits tool_use per state update plus a final tool_result —
        counting both would double-count, so tool_result takes precedence."""
        td = tmp_path / "tasks" / "task-tr"
        td.mkdir(parents=True)
        _write_task_json(td)
        evs = [
            _event(ts="2025-01-01T10:00:00Z", kind="tool_use", tool_name="bash"),
            _event(ts="2025-01-01T10:00:01Z", kind="tool_use", tool_name="bash"),
            _event(ts="2025-01-01T10:00:02Z", kind="tool_result", tool_name="bash"),
        ]
        _write_events(td, evs)

        r = task_record_cached(td)
        assert r["tool_counts"] == {"bash": 1}


class TestMissingEvents:
    """Test 3: task.json but no events.jsonl."""

    def test_no_events(self, tmp_path: Path) -> None:
        td = tmp_path / "tasks" / "task-empty"
        td.mkdir(parents=True)
        _write_task_json(td)

        r = task_record_cached(td)
        assert r["id"] == "task-empty"
        assert r["first_ts"] is None
        assert r["last_ts"] is None
        assert r["events"] == 0
        assert r["steps"] == 0
        assert r["segments"] == 0
        assert r["errors"] == 0
        assert r["tool_counts"] == {}
        assert r["output_tokens"] == 0
        assert r["input_tokens"] == 0
        assert r["cache_creation_tokens"] == 0
        assert r["cache_read_tokens"] == 0
        assert r["peak_context_tokens"] is None
        assert r["rate_limited"] == 0
        assert r["hour_hist"] == {}


class TestCache:
    """Test 4: repeated calls agree; append changes the result.

    The events.jsonl scan itself is cached in state.events.scan_cached;
    task_record_cached rebuilds the (cheap) record dict from that plus
    task.json on every call.
    """

    def test_cache_returns_equal_record(self, tmp_path: Path) -> None:
        td = tmp_path / "tasks" / "task-cache"
        td.mkdir(parents=True)
        _write_task_json(td)
        _write_events(
            td,
            [_event(ts="2025-06-01T09:00:00Z", kind="session_started", session_id="x")],
        )

        r1 = task_record_cached(td)
        r2 = task_record_cached(td)
        assert r1 == r2

    def test_cache_invalidation_on_append(self, tmp_path: Path) -> None:
        td = tmp_path / "tasks" / "task-cache2"
        td.mkdir(parents=True)
        _write_task_json(td)
        _write_events(
            td,
            [_event(ts="2025-06-01T10:00:00Z", kind="session_started", session_id="a")],
        )

        r1 = task_record_cached(td)
        assert r1["events"] == 1

        # Append a line (changes file size)
        evs = "\n".join(
            [
                _event(ts="2025-06-01T10:00:00Z", kind="session_started", session_id="a"),
                _event(ts="2025-06-01T11:00:00Z", kind="session_started", session_id="b"),
            ]
        )
        (td / "attempts" / "1" / "events.jsonl").write_text(evs + "\n", "utf-8")

        r2 = task_record_cached(td)
        # Must be a different object (cache invalidated)
        assert r1 is not r2
        assert r2["events"] == 2


class TestCollectRecords:
    """Test 5: collect_records skips dirs without task.json."""

    def test_skips_no_task_json(self, tmp_path: Path) -> None:
        home = tmp_path
        tasks = home / "tasks"

        # Dir with task.json
        td1 = tasks / "task-a"
        td1.mkdir(parents=True)
        _write_task_json(td1)

        # Dir without task.json
        td2 = tasks / "task-b"
        td2.mkdir(parents=True)
        _write_events(td2, [_event(ts="2025-01-01T00:00:00Z", kind="session_started")])

        # Dir that is not a directory
        not_dir = tasks / "not-a-dir"
        not_dir.touch()

        records = collect_records(home)
        ids = [r["id"] for r in records]
        assert "task-a" in ids
        assert "task-b" not in ids
        assert len(records) == 1
