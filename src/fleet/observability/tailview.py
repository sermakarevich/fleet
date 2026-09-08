"""render_event and render_lines — human-readable events.jsonl rendering.

Rendering rules by normalised ``evt["kind"]``:

- ``session_started`` -- ``── session <last8> started ──`` (deduped)
- ``tool_use``        -- ``▶ <tool> <input>``
- ``tool_result``     -- ``✓ <tool> <output>``
- ``error``            -- ``✗ <tool> <detail>``
- ``assistant_text``  -- ``💬 <text>`` or ``· step in=<i> tok``
- ``session_ended``   -- ``── session ended … ──``
- anything else       -- ``None`` (skipped)
"""

from __future__ import annotations

import json
from datetime import datetime

_SID_SHORT_LEN = 8  # how many trailing session-id chars to show in the divider


def _ts_prefix(evt: dict) -> str:
    ts_str = evt.get("ts")
    if isinstance(ts_str, str):
        try:
            dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            return dt.strftime("%H:%M:%S")
        except (ValueError, OSError):
            pass
    return "--:--:--"


def _compact_json(obj: object) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def render_event(evt: dict, state: dict) -> str | None:  # noqa: PLR0911, PLR0912, PLR0915  # ADR 0006 bead 25
    """Render one parsed events.jsonl line, or None to skip.

    *state* is a mutable dict carrying renderer state across calls
    (currently just *last_session*).
    """
    kind = evt.get("kind")
    _ts_prefix(evt)
    raw = evt.get("raw") or {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            raw = {}

    # ---- session_started ----------------------------------------------------
    if kind == "session_started":
        sid = evt.get("session_id") or raw.get("sessionID")
        if sid is None:
            return None
        last = state.get("last_session")
        if last is not None and last == sid:
            return None  # deduplicate real session changes (opencode emits one
            # step_start per LLM step — dozens per run)
        state["last_session"] = sid
        last8 = sid[-_SID_SHORT_LEN:] if len(sid) >= _SID_SHORT_LEN else sid
        return f"\u2500\u2500 session {last8} started \u2500\u2500"

    # ---- tool_use -----------------------------------------------------------
    if kind == "tool_use":
        tool = evt.get("tool_name") or "?"
        inp = None
        if isinstance(raw, dict):
            part = raw.get("part")
            if isinstance(part, dict):
                st = part.get("state")
                if isinstance(st, dict):
                    inp = st.get("input")
            if inp is None:
                inp = raw.get("input")
        if inp is not None:
            inp_str = _compact_json(inp)[:100]
            return f"\u25b6 {tool} {inp_str}"
        return f"\u25b6 {tool}"

    # ---- tool_result --------------------------------------------------------
    if kind == "tool_result":
        tool = evt.get("tool_name") or "?"
        out = None
        if isinstance(raw, dict):
            part = raw.get("part")
            if isinstance(part, dict):
                st = part.get("state")
                if isinstance(st, dict):
                    out = st.get("output")
        if out is not None:
            out_str = " ".join(str(out).split())[:100]
            return f"\u2713 {tool} {out_str}"
        return f"\u2713 {tool}"

    # ---- error --------------------------------------------------------------
    if kind == "error":
        tool = evt.get("tool_name") or "error"
        err = None
        if isinstance(raw, dict):
            part = raw.get("part")
            if isinstance(part, dict):
                st = part.get("state")
                if isinstance(st, dict):
                    err = st.get("error")
        if err is not None:
            return f"\u2717 {tool} {err}"
        detail = json.dumps(raw, ensure_ascii=False)[:150]
        return f"\u2717 {tool} {detail}"

    # ---- assistant_text -----------------------------------------------------
    if kind == "assistant_text":
        text = None
        # opencode shape
        if raw.get("type") == "text" and isinstance(raw, dict):
            part = raw.get("part")
            if isinstance(part, dict):
                t = part.get("text")
                if t is not None:
                    text = str(t)
        # fall-back: raw.text
        if text is None and isinstance(raw, dict):
            t = raw.get("text")
            if t is not None:
                text = str(t)
        # claude shape: message.content as list
        if text is None and isinstance(raw, dict):
            msg = raw.get("message")
            if isinstance(msg, dict):
                content = msg.get("content")
                if isinstance(content, list):
                    pieces: list[str] = []
                    for item in content:
                        if isinstance(item, dict) and item.get("type") == "text":
                            t = item.get("text")
                            if t is not None:
                                pieces.append(str(t))
                    if pieces:
                        text = " ".join(pieces)
        if text is not None:
            collapsed = " ".join(text.split())[:160]
            return f"\U0001f4ac {collapsed}"
        usage = evt.get("usage")
        if usage is not None:
            in_tok = usage.get("input_tokens")
            if in_tok is not None:
                return f"\u00b7 step in={in_tok} tok"
        return None

    # ---- session_ended ------------------------------------------------------
    if kind == "session_ended":
        usage = evt.get("usage")
        if usage is not None and isinstance(usage, dict):
            in_t = usage.get("input_tokens")
            out_t = usage.get("output_tokens")
            in_s = str(in_t) if in_t is not None else "?"
            out_s = str(out_t) if out_t is not None else "?"
            return f"\u2500\u2500 session ended (in={in_s} out={out_s}) \u2500\u2500"
        return "\u2500\u2500 session ended \u2500\u2500"

    return None


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


def event_summary(kind: str, raw: dict, tool_name: str | None = None) -> str:  # noqa: PLR0911, PLR0912, PLR0915  # ADR 0006 bead 25
    """Derive a ~200-char one-line summary from a raw event dict.

    Used by GET /api/tasks/{id}/events to render a compact preview per row.
    """
    if kind == "assistant_text":
        text = None
        part = raw.get("part")
        if isinstance(part, dict):
            t = part.get("text")
            if t is not None:
                text = str(t)
        if text is None and isinstance(raw, dict):
            t = raw.get("text")
            if t is not None:
                text = str(t)
        if text:
            return " ".join(text.split())[:200]
        usage = raw.get("usage", {})
        if isinstance(usage, dict):
            in_t = usage.get("input_tokens")
            out_t = usage.get("output_tokens")
            parts = []
            if in_t is not None:
                parts.append(f"in={in_t}")
            if out_t is not None:
                parts.append(f"out={out_t}")
            if parts:
                return "Tokens: " + ", ".join(parts)
        return ""
    if kind == "tool_use":
        tool = tool_name or raw.get("tool", "") or ""
        inp = None
        state = raw.get("state")
        if isinstance(state, dict):
            inp = state.get("input")
        if inp is None:
            part = raw.get("part")
            if isinstance(part, dict):
                ps = part.get("state", {})
                if isinstance(ps, dict):
                    inp = ps.get("input")
        if isinstance(inp, dict | list):
            return json.dumps(
                {"tool": tool, "input": inp},
                ensure_ascii=False,
                separators=(",", ":"),
            )[:200]
        if inp is not None:
            return tool + " " + str(inp)[:200]
        return tool
    if kind == "tool_result":
        tool = tool_name or raw.get("tool", "") or ""
        state = raw.get("state", {})
        out_str = ""
        if isinstance(state, dict):
            out = state.get("output")
            if out is not None:
                out_str = out[:200] if isinstance(out, str) else str(out)[:200]
        if out_str:
            return tool + " " + out_str
        return tool
    if kind == "error":
        err = None
        part = raw.get("part")
        if isinstance(part, dict):
            st = part.get("state", {})
            if isinstance(st, dict):
                err = st.get("error")
        if err is None and isinstance(raw, dict):
            err = raw.get("error") or raw.get("message")
        display_tool = tool_name or raw.get("tool", "") or ""
        if display_tool:
            if err is not None:
                return display_tool + ": " + str(err)[:200]
            return display_tool + ": " + json.dumps(raw, ensure_ascii=False)[:200]
        if err is not None:
            return "Error: " + str(err)[:200]
        return "Error: " + json.dumps(raw, ensure_ascii=False)[:200]
    if kind == "session_started":
        sid = raw.get("sessionID", "") or raw.get("session_id", "") or ""
        last8 = str(sid)[-8:] if sid else "?"
        return "Step start (session " + last8 + ")"
    if kind == "session_ended":
        tokens = raw.get("tokens", {})
        if isinstance(tokens, dict):
            in_t = tokens.get("input")
            out_t = tokens.get("output")
            parts = []
            if in_t is not None:
                parts.append(f"in={in_t}")
            if out_t is not None:
                parts.append(f"out={out_t}")
            if parts:
                return "Session end (" + ", ".join(parts) + ")"
        return "Session end"
    return ""
