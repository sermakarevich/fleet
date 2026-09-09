from __future__ import annotations

import json
from pathlib import Path

from fleet.state.events import (
    EventScanCache,
    event_stats,
    event_stats_cached,
    iter_events,
    parse_iso,
    safe_int,
)


def _event(**kw) -> str:
    return json.dumps(kw)


def _write_events(d: Path, lines: list[str], n: int = 1) -> None:
    attempt_dir = d / "attempts" / str(n)
    attempt_dir.mkdir(parents=True, exist_ok=True)
    (attempt_dir / "events.jsonl").write_text("\n".join(lines) + "\n", "utf-8")


def test_parse_iso_valid_and_invalid() -> None:
    assert parse_iso("2025-01-01T00:00:00Z") is not None
    assert parse_iso("not-a-date") is None


def test_safe_int() -> None:
    assert safe_int(5) == 5
    assert safe_int("7") == 7
    assert safe_int("nope") == 0
    assert safe_int(True) == 0
    assert safe_int(None) == 0


def test_iter_events_tolerant_of_bad_lines(tmp_path: Path) -> None:
    d = tmp_path / "task-1"
    _write_events(
        d,
        [
            _event(kind="tool_use", ts="2025-01-01T00:00:00Z"),
            "",
            "NOT JSON",
            _event(kind="tool_result", ts="2025-01-01T00:00:01Z"),
        ],
    )
    rows = list(iter_events(d))
    assert len(rows) == 2
    assert rows[0]["kind"] == "tool_use"
    assert rows[1]["kind"] == "tool_result"


def test_iter_events_missing_file(tmp_path: Path) -> None:
    assert list(iter_events(tmp_path / "missing")) == []


def test_scan_counts_and_last_kind(tmp_path: Path) -> None:
    d = tmp_path / "task-2"
    _write_events(
        d,
        [
            _event(
                ts="2025-01-01T10:00:00Z",
                kind="tool_use",
                tool_name="Read",
                raw={"input": {"file_path": "/a.py"}},
            ),
            _event(
                ts="2025-01-01T10:01:00Z",
                kind="tool_result",
                tool_name="Read",
                usage={
                    "input_tokens": 100,
                    "output_tokens": 50,
                    "cache_creation_input_tokens": 10,
                    "cache_read_input_tokens": 5,
                },
            ),
            _event(
                ts="2025-01-01T10:02:00Z",
                kind="tool_use",
                tool_name="Edit",
                raw={"input": {"file_path": "/a.py"}},
            ),
            "GARBAGE",
        ],
    )
    stats = event_stats(d)
    assert stats.event_count == 3
    assert stats.last_kind == "tool_use"
    assert stats.last_detail == "Edit"
    assert stats.tool_counts == {"Read": 1}
    assert stats.output_tokens == 50
    assert stats.input_tokens == 100
    assert stats.cache_creation_tokens == 10
    assert stats.cache_read_tokens == 5
    assert stats.peak_context_tokens == 115
    assert stats.files_touched["/a.py"].read == 1
    assert stats.files_touched["/a.py"].edit == 1
    assert stats.files_touched_count == 1
    assert stats.first_ts is not None
    assert stats.last_ts is not None


def test_scan_rate_limit_events(tmp_path: Path) -> None:
    d = tmp_path / "task-3"
    _write_events(
        d,
        [
            _event(
                ts="2025-01-01T00:00:00Z",
                kind="rate_limit",
                rate_info={
                    "status": "rejected",
                    "provider": "anthropic",
                    "resets_at": 1735689660.0,
                },
            ),
            _event(
                ts="2025-01-01T00:00:00Z",
                kind="rate_limit_info",
                rate_info={"status": "approaching"},
            ),
        ],
    )
    stats = event_stats(d)
    assert stats.rate_limited == 1
    assert len(stats.rate_limit_events) == 1
    assert stats.rate_limit_events[0]["provider"] == "anthropic"
    assert stats.rate_limit_events[0]["duration_sec"] == 60.0


def test_scan_empty_dir(tmp_path: Path) -> None:
    stats = event_stats(tmp_path / "no-such-task")
    assert stats.event_count == 0
    assert stats.first_ts is None
    assert stats.tool_counts == {}
    assert stats.files_touched == {}


def test_event_stats_cached_reuses_until_file_changes(tmp_path: Path) -> None:
    d = tmp_path / "task-4"
    _write_events(d, [_event(ts="2025-01-01T00:00:00Z", kind="session_started")])
    cache = EventScanCache()

    s1 = event_stats_cached(d, cache)
    s2 = event_stats_cached(d, cache)
    assert s1 is s2

    with (d / "attempts" / "1" / "events.jsonl").open("a") as fh:
        fh.write(_event(ts="2025-01-01T00:00:01Z", kind="session_started") + "\n")

    s3 = event_stats_cached(d, cache)
    assert s3 is not s1
    assert s3.event_count == 2


def test_event_stats_cached_without_cache_always_rescans(tmp_path: Path) -> None:
    d = tmp_path / "task-5"
    _write_events(d, [_event(ts="2025-01-01T00:00:00Z", kind="session_started")])

    s1 = event_stats_cached(d)
    s2 = event_stats_cached(d)
    assert s1 is not s2
    assert s1.event_count == s2.event_count == 1
