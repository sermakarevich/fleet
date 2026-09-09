"""Human-readable events.jsonl rendering for the terminal.

Both entry points delegate to observability/event_render.py's EVENT_RENDER
table (one renderer per event kind, producing (summary, detail)):
render_event returns the detail line with session-start dedup across
calls, render_lines timestamps a batch, event_summary returns the summary
preview the serve API stores per event row.
"""

from __future__ import annotations

import json

from fleet.core.iso import parse_iso
from fleet.core.task import EventKind

from .event_render import render


def _ts_prefix(event: dict) -> str:
    """HH:MM:SS from the event timestamp, placeholder when unparseable."""
    ts_str = event.get("ts")
    if isinstance(ts_str, str):
        dt = parse_iso(ts_str)
        if dt is not None:
            return dt.strftime("%H:%M:%S")
    return "--:--:--"


def render_event(event: dict, state: dict) -> str | None:
    """Render one parsed events.jsonl line, or None to skip.

    *state* is a mutable dict carrying renderer state across calls
    (currently just *last_session*).
    """
    kind = event.get("kind")
    if not isinstance(kind, str):
        return None
    raw = event.get("raw") or {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            raw = {}
    if kind == EventKind.SESSION_STARTED:
        sid = event.get("session_id") or (raw.get("sessionID") if isinstance(raw, dict) else None)
        if sid is None or state.get("last_session") == sid:
            return None
        state["last_session"] = sid
    _summary, detail = render(kind, {**event, "raw": raw})
    return detail


def render_lines(lines: list[str]) -> list[str]:
    """json.loads each line (skip unparseable lines silently), call render_event,
    collect non-None results. All lines share one state dict for dedup."""
    state: dict = {"last_session": None}
    results: list[str] = []
    for raw_line in lines:
        stripped = raw_line.strip()
        if not stripped:
            continue
        try:
            evt = json.loads(stripped)
        except (json.JSONDecodeError, ValueError):
            continue
        rendered = render_event(evt, state)
        if rendered is not None:
            results.append(_ts_prefix(evt) + " " + rendered)
    return results


def event_summary(kind: str, raw: dict, tool_name: str | None = None) -> str:
    """Derive a ~200-char one-line summary from a raw event dict.

    Used by GET /api/tasks/{id}/events to render a compact preview per row.
    """
    sid = None
    if isinstance(raw, dict):
        sid = raw.get("sessionID") or raw.get("session_id")
    evt = {
        "kind": kind,
        "tool_name": tool_name,
        "session_id": sid or None,
        "usage": raw.get("usage") if isinstance(raw, dict) else None,
        "raw": raw,
    }
    summary, _detail = render(kind, evt)
    return summary
