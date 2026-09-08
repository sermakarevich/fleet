"""One table rendering fleet worker events for humans.

EVENT_RENDER maps a normalised event kind to a renderer producing
``(summary, detail)``: *summary* is the ~200-char one-line preview the
serve API stores per event row, *detail* is the terminal line (or None to
skip the event). Called by observability/tailview.py (render_event uses
detail, event_summary uses summary) so both stay identical by
construction. Input is one normalised dict with kind, session_id,
tool_name, usage and raw.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

Renderer = Callable[[dict], tuple[str, str | None]]

_SID_SHORT_LEN = 8  # trailing session-id chars shown in dividers


def _compact_json(obj: object) -> str:
    """Single-line JSON for embedding values in a rendered line."""
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def _session_short(sid: str) -> str:
    """Last few chars of a session id for tight dividers."""
    return sid[-_SID_SHORT_LEN:] if len(sid) >= _SID_SHORT_LEN else sid


def render_session_started(evt: dict) -> tuple[str, str | None]:
    """Session divider pair; detail None when no session id is known."""
    sid = evt.get("session_id") or (evt.get("raw") or {}).get("sessionID")
    if not sid:
        return "Step start (session ?)", None
    short = _session_short(str(sid))
    return f"Step start (session {short})", f"\u2500\u2500 session {short} started \u2500\u2500"


def render_tool_use(evt: dict) -> tuple[str, str | None]:
    """Tool call pair: JSON preview plus the ▶ terminal line."""
    raw = evt.get("raw") or {}
    state = raw.get("state") if isinstance(raw.get("state"), dict) else None
    part = raw.get("part") if isinstance(raw.get("part"), dict) else None
    part_state = part.get("state") if part and isinstance(part.get("state"), dict) else None
    summary_in = state.get("input") if state else None
    if summary_in is None and isinstance(part_state, dict):
        summary_in = part_state.get("input")
    summary_tool = evt.get("tool_name") or raw.get("tool", "") or ""
    if isinstance(summary_in, dict | list):
        summary = _compact_json({"tool": summary_tool, "input": summary_in})[:200]
    elif summary_in is not None:
        summary = summary_tool + " " + str(summary_in)[:200]
    else:
        summary = summary_tool
    detail_tool = evt.get("tool_name") or "?"
    detail_in = part_state.get("input") if isinstance(part_state, dict) else None
    if detail_in is None:
        detail_in = raw.get("input")
    if detail_in is None:
        return summary, f"\u25b6 {detail_tool}"
    return summary, f"\u25b6 {detail_tool} {_compact_json(detail_in)[:100]}"


def render_tool_result(evt: dict) -> tuple[str, str | None]:
    """Tool result pair: plain preview plus the ✓ terminal line."""
    raw = evt.get("raw") or {}
    state = raw.get("state", {})
    out_str = ""
    if isinstance(state, dict) and state.get("output") is not None:
        out = state["output"]
        out_str = out[:200] if isinstance(out, str) else str(out)[:200]
    tool = evt.get("tool_name") or raw.get("tool", "") or ""
    summary = tool + " " + out_str if out_str else tool
    part = raw.get("part") if isinstance(raw.get("part"), dict) else None
    part_state = part.get("state") if part and isinstance(part.get("state"), dict) else None
    out = part_state.get("output") if part_state else None
    if out is None:
        return summary, f"\u2713 {evt.get('tool_name') or '?'}"
    collapsed = " ".join(str(out).split())[:100]
    return summary, f"\u2713 {evt.get('tool_name') or '?'} {collapsed}"


def render_error(evt: dict) -> tuple[str, str | None]:
    """Error pair: 'tool: detail' preview plus the ✗ terminal line."""
    raw = evt.get("raw") or {}
    part = raw.get("part") if isinstance(raw.get("part"), dict) else None
    part_state = part.get("state") if part and isinstance(part.get("state"), dict) else None
    err = part_state.get("error") if part_state else None
    detail_err = err
    if err is None and isinstance(raw, dict):
        err = raw.get("error") or raw.get("message")
    tool = evt.get("tool_name") or raw.get("tool", "") or ""
    if tool:
        summary = tool + ": " + (str(err)[:200] if err is not None else _compact_json(raw)[:200])
    elif err is not None:
        summary = "Error: " + str(err)[:200]
    else:
        summary = "Error: " + _compact_json(raw)[:200]
    detail_tool = evt.get("tool_name") or "error"
    if detail_err is not None:
        return summary, f"\u2717 {detail_tool} {detail_err}"
    return summary, f"\u2717 {detail_tool} {json.dumps(raw, ensure_ascii=False)[:150]}"


def _summary_text(raw: dict) -> str | None:
    """Assistant prose for the API preview (part text, else raw text)."""
    part = raw.get("part") if isinstance(raw.get("part"), dict) else None
    if part is not None and part.get("text") is not None:
        return str(part["text"])
    if raw.get("text") is not None:
        return str(raw["text"])
    return None


def _detail_text(raw: dict) -> str | None:
    """Assistant prose for the terminal (opencode shapes, else claude content)."""
    if raw.get("type") == "text":
        part = raw.get("part") if isinstance(raw.get("part"), dict) else None
        if part is not None and part.get("text") is not None:
            return str(part["text"])
    if raw.get("text") is not None:
        return str(raw["text"])
    msg = raw.get("message") if isinstance(raw.get("message"), dict) else None
    content = msg.get("content") if msg else None
    if isinstance(content, list):
        pieces = [str(item["text"]) for item in content if _is_text_part(item)]
        if pieces:
            return " ".join(pieces)
    return None


def _is_text_part(item: object) -> bool:
    """True when a claude content item carries usable text."""
    if not isinstance(item, dict):
        return False
    return item.get("type") == "text" and item.get("text") is not None


def _token_bits(usage: Any) -> list[str]:
    """['in=N', 'out=M'] for whatever usage block is present."""
    if not isinstance(usage, dict):
        return []
    bits = []
    if usage.get("input_tokens") is not None:
        bits.append(f"in={usage['input_tokens']}")
    if usage.get("output_tokens") is not None:
        bits.append(f"out={usage['output_tokens']}")
    return bits


def render_assistant_text(evt: dict) -> tuple[str, str | None]:
    """Assistant text pair: prose preview (or token counts) plus 💬 line."""
    raw = evt.get("raw") or {}
    text = _summary_text(raw)
    summary = " ".join(text.split())[:200] if text else ""
    if not summary:
        bits = _token_bits(evt.get("usage"))
        summary = "Tokens: " + ", ".join(bits) if bits else ""
    detail_text = _detail_text(raw if isinstance(raw, dict) else {})
    if detail_text is not None:
        return summary, f"\U0001f4ac {' '.join(detail_text.split())[:160]}"
    usage = evt.get("usage")
    in_tok = usage.get("input_tokens") if isinstance(usage, dict) else None
    if in_tok is not None:
        return summary, f"\u00b7 step in={in_tok} tok"
    return summary, None


def render_session_ended(evt: dict) -> tuple[str, str | None]:
    """Session end pair: token-count preview plus the ended divider."""
    raw = evt.get("raw") or {}
    tokens = raw.get("tokens", {})
    bits = []
    if isinstance(tokens, dict):
        if tokens.get("input") is not None:
            bits.append(f"in={tokens['input']}")
        if tokens.get("output") is not None:
            bits.append(f"out={tokens['output']}")
    summary = "Session end (" + ", ".join(bits) + ")" if bits else "Session end"
    usage = evt.get("usage")
    if usage is not None and isinstance(usage, dict):
        in_s = str(usage["input_tokens"]) if usage.get("input_tokens") is not None else "?"
        out_s = str(usage["output_tokens"]) if usage.get("output_tokens") is not None else "?"
        return summary, f"\u2500\u2500 session ended (in={in_s} out={out_s}) \u2500\u2500"
    return summary, "\u2500\u2500 session ended \u2500\u2500"


EVENT_RENDER: dict[str, Renderer] = {
    "session_started": render_session_started,
    "tool_use": render_tool_use,
    "tool_result": render_tool_result,
    "error": render_error,
    "assistant_text": render_assistant_text,
    "session_ended": render_session_ended,
}


def render(kind: str, evt: dict) -> tuple[str, str | None]:
    """Render *evt* of *kind*; ("", None) for unknown kinds (skip)."""
    renderer = EVENT_RENDER.get(kind)
    if renderer is None:
        return "", None
    return renderer(evt)
