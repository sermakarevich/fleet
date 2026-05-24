from datetime import datetime, timezone

from fleet.schemas import Event


def _ts() -> datetime:
    return datetime.now(tz=timezone.utc)


def test_event_required_fields():
    e = Event(kind="assistant_text", raw={"type": "assistant"}, ts=_ts())
    assert e.kind == "assistant_text"
    assert e.raw == {"type": "assistant"}
    assert isinstance(e.ts, datetime)


def test_event_optional_fields_default_none():
    e = Event(kind="tool_use", raw={}, ts=_ts())
    assert e.session_id is None
    assert e.tool_name is None
    assert e.usage is None
    assert e.rate_info is None
    assert e.extra == {}


def test_event_with_all_fields():
    ts = _ts()
    e = Event(
        kind="rate_limit_info",
        raw={"type": "rate_limit_event"},
        ts=ts,
        session_id="sess_abc",
        tool_name=None,
        usage={"input_tokens": 100, "output_tokens": 50},
        rate_info={"usage_pct": 75.0, "resets_at": 1748000000, "status": "approaching"},
        extra={"custom_key": "value"},
    )
    assert e.kind == "rate_limit_info"
    assert e.session_id == "sess_abc"
    assert e.usage["input_tokens"] == 100
    assert e.rate_info["usage_pct"] == 75.0
    assert e.extra["custom_key"] == "value"


def test_all_event_kinds_are_valid():
    valid_kinds = [
        "assistant_text", "tool_use", "tool_result", "thinking",
        "rate_limit", "rate_limit_info", "context_pressure",
        "session_started", "session_ended", "error", "result",
    ]
    for kind in valid_kinds:
        e = Event(kind=kind, raw={}, ts=_ts())
        assert e.kind == kind


def test_event_extra_is_independent_per_instance():
    e1 = Event(kind="error", raw={}, ts=_ts())
    e2 = Event(kind="error", raw={}, ts=_ts())
    e1.extra["k"] = "v"
    assert "k" not in e2.extra
