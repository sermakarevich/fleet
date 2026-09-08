"""Every EVENT_RENDER kind renders on a minimal dict.

Rows are (kind, event, expected summary, expected detail): the table must
never crash on sparse input, unknown kinds render ("", None), and the two
tailview wrappers return the matching half of the pair.
"""

from __future__ import annotations

import pytest

from fleet.observability.event_render import EVENT_RENDER, render
from fleet.observability.tailview import event_summary, render_event


def _evt(kind: str, raw: dict | None = None, **fields: object) -> dict:
    """Minimal normalised event: kind plus whatever the renderer reads."""
    evt: dict = {
        "kind": kind,
        "session_id": None,
        "tool_name": None,
        "usage": None,
        "raw": raw or {},
    }
    evt.update(fields)
    return evt


RENDER_CASES = [
    # (kind, event, expected summary, expected detail)
    (
        "session_started",
        _evt("session_started", {"sessionID": "abc12345"}, session_id="abc12345"),
        "Step start (session abc12345)",
        "\u2500\u2500 session abc12345 started \u2500\u2500",
    ),
    (
        "session_started",
        _evt("session_started", {}),
        "Step start (session ?)",
        None,
    ),
    (
        "tool_use",
        _evt("tool_use", {"part": {"state": {"input": {"a": 1}}}}, tool_name="Read"),
        '{"tool":"Read","input":{"a":1}}',
        '\u25b6 Read {"a":1}',
    ),
    (
        "tool_use",
        _evt("tool_use", {}),
        "",
        "\u25b6 ?",
    ),
    (
        "tool_result",
        _evt(
            "tool_result",
            {"state": {"output": "done"}, "part": {"state": {"output": "done"}}},
            tool_name="Bash",
        ),
        "Bash done",
        "\u2713 Bash done",
    ),
    (
        "error",
        _evt("error", {"part": {"state": {"error": "boom"}}}, tool_name="Bash"),
        "Bash: boom",
        "\u2717 Bash boom",
    ),
    (
        "error",
        _evt("error", {"message": "kaput"}),
        "Error: kaput",
        '\u2717 error {"message": "kaput"}',
    ),
    (
        "assistant_text",
        _evt("assistant_text", {"type": "text", "part": {"text": "hello there"}}),
        "hello there",
        "\U0001f4ac hello there",
    ),
    (
        "assistant_text",
        _evt("assistant_text", {}, usage={"input_tokens": 10}),
        "Tokens: in=10",
        "\u00b7 step in=10 tok",
    ),
    (
        "assistant_text",
        _evt("assistant_text", {}),
        "",
        None,
    ),
    (
        "session_ended",
        _evt("session_ended", {}, usage={"input_tokens": 3, "output_tokens": 7}),
        "Session end",
        "\u2500\u2500 session ended (in=3 out=7) \u2500\u2500",
    ),
    (
        "session_ended",
        _evt("session_ended", {"tokens": {"input": 1}}),
        "Session end (in=1)",
        "\u2500\u2500 session ended \u2500\u2500",
    ),
    (
        "mystery_kind",
        _evt("mystery_kind", {}),
        "",
        None,
    ),
]


@pytest.mark.parametrize(("kind", "evt", "summary", "detail"), RENDER_CASES)
def test_event_render_table(kind: str, evt: dict, summary: str, detail: str | None) -> None:
    """The table renders every known kind and skips unknown ones."""
    assert render(kind, evt) == (summary, detail)


def test_event_render_covers_expected_kinds() -> None:
    """No kind silently missing from the registry."""
    assert set(EVENT_RENDER) == {
        "session_started",
        "tool_use",
        "tool_result",
        "error",
        "assistant_text",
        "session_ended",
    }


def test_tailview_wrappers_return_matching_halves() -> None:
    """render_event yields detail, event_summary yields summary, same pair."""
    evt = _evt("tool_use", {"part": {"state": {"input": {"a": 1}}}}, tool_name="Read")
    summary, detail = render("tool_use", evt)
    assert render_event(dict(evt), {}) == detail
    assert event_summary("tool_use", dict(evt["raw"]), "Read") == summary


def test_render_event_dedups_session_started() -> None:
    """Second divider for the same session is skipped via state."""
    state: dict = {}
    evt = _evt("session_started", {"sessionID": "s1"}, session_id="s1")
    first = render_event(dict(evt), state)
    assert first is not None and "started" in first
    assert render_event(dict(evt), state) is None
