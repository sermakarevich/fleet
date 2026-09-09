"""Tests for observability/tailview.py. Mirrors the source path."""

from __future__ import annotations

import json

from fleet.observability.tailview import render_lines


def test_render_lines_prefix_every_line_with_timestamp() -> None:
    """Rendered batch lines carry an HH:MM:SS prefix from the event ts."""
    lines = [
        json.dumps(
            {
                "kind": "assistant_text",
                "ts": "2026-09-08T10:11:12+00:00",
                "raw": {"type": "text", "part": {"text": "hello"}},
            }
        )
    ]
    rendered = render_lines(lines)
    assert len(rendered) == 1
    assert rendered[0].startswith("10:11:12 ")


def test_render_lines_uses_placeholder_for_bad_timestamp() -> None:
    """Unparseable timestamps still render, with the placeholder prefix."""
    lines = [json.dumps({"kind": "error", "ts": "nonsense", "raw": {"error": "boom"}})]
    rendered = render_lines(lines)
    assert len(rendered) == 1
    assert rendered[0].startswith("--:--:-- ")
