"""Tests for one visitor class each in state/events.py. Mirrors the source path."""

from __future__ import annotations

from fleet.state.events import (
    VISITORS,
    ContextPressureVisitor,
    CountVisitor,
    ErrorVisitor,
    EventStats,
    EventVisitor,
    LastEventVisitor,
    RateLimitVisitor,
    SessionVisitor,
    TimingVisitor,
    ToolCallVisitor,
    UsageVisitor,
    stats_from_rows,
)


def _run(visitor: EventVisitor, rows: list[dict]):
    for row in rows:
        visitor.visit(row)
    return visitor.result()


def test_count_visitor_counts_every_row() -> None:
    rows = [{"kind": "tool_use"}, {"kind": "error"}, {"no": "kind"}]
    assert _run(CountVisitor(), rows) == 3


def test_timing_visitor_range_and_histogram() -> None:
    rows = [
        {"ts": "2025-01-01T10:00:00Z"},
        {"ts": "2025-01-01T10:05:00Z"},
        {"ts": "2025-01-01T11:00:00Z"},
    ]
    timing = _run(TimingVisitor(), rows)
    assert timing.first_ts is not None and timing.last_ts is not None
    assert timing.first_ts < timing.last_ts
    assert timing.hour_hist == {"2-10": 2, "2-11": 1}


def test_last_event_visitor_remembers_tool() -> None:
    rows = [
        {"kind": "tool_use", "tool_name": "Read"},
        {"kind": "tool_result", "tool_name": "Read"},
        {"kind": "error"},
    ]
    last = _run(LastEventVisitor(), rows)
    assert last.kind == "error"
    assert last.detail is None


def test_session_visitor_steps_and_segments() -> None:
    rows = [
        {"kind": "session_started", "session_id": "a"},
        {"kind": "tool_use", "session_id": "a"},
        {"kind": "session_started", "session_id": "b"},
    ]
    session = _run(SessionVisitor(), rows)
    assert session.steps == 2
    assert session.segments == 2


def test_error_visitor_counts_errors() -> None:
    rows = [{"kind": "error"}, {"kind": "tool_use"}, {"kind": "error"}]
    assert _run(ErrorVisitor(), rows) == 2


def test_tool_call_visitor_results_win_and_files() -> None:
    rows = [
        {"kind": "tool_use", "tool_name": "Read", "raw": {"input": {"file_path": "/a.py"}}},
        {"kind": "tool_use", "tool_name": "Edit", "raw": {"input": {"file_path": "/a.py"}}},
        {"kind": "tool_result", "tool_name": "Read"},
    ]
    tools = _run(ToolCallVisitor(), rows)
    assert tools.tool_counts == {"Read": 1}
    assert tools.files_touched["/a.py"].read == 1
    assert tools.files_touched["/a.py"].edit == 1


def test_usage_visitor_sums_and_peak() -> None:
    rows = [
        {"kind": "tool_use", "usage": {"input_tokens": 100, "output_tokens": 50}},
        {"kind": "tool_use", "usage": {"input_tokens": 200, "output_tokens": 10}},
        {"kind": "session_ended", "usage": {"input_tokens": 9999, "output_tokens": 9999}},
    ]
    usage = _run(UsageVisitor(), rows)
    assert usage.input_tokens == 300
    assert usage.output_tokens == 60
    assert usage.peak_context_tokens == 200
    assert usage.current_context_tokens == 200


def test_rate_limit_visitor_collects_rejected() -> None:
    rows = [
        {
            "ts": "2025-01-01T00:00:00Z",
            "kind": "rate_limit",
            "rate_info": {"status": "rejected", "provider": "anthropic", "resets_at": 1735689660.0},
        },
        {"kind": "rate_limit_info", "rate_info": {"status": "approaching"}},
        {"kind": "tool_use"},
    ]
    rate = _run(RateLimitVisitor(), rows)
    assert rate.limited == 1
    assert rate.events[0]["provider"] == "anthropic"
    assert rate.events[0]["duration_sec"] == 60.0


def test_context_pressure_visitor_latches() -> None:
    rows = [{"kind": "tool_use"}, {"kind": "context_pressure"}, {"kind": "tool_use"}]
    assert _run(ContextPressureVisitor(), rows) is True


def test_visitors_cover_stats_from_rows() -> None:
    """Every VISITORS entry is a visitor, and an empty scan is all defaults."""
    assert VISITORS
    for visitor_cls in VISITORS:
        assert issubclass(visitor_cls, EventVisitor)
    assert stats_from_rows(iter([])) == EventStats()
