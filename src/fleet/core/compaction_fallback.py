"""Deterministic compaction fallback: bounded STATE.md without a model.

Pure: no I/O, no subprocess. Used by ``workers/compact.py`` when the cheap
model call fails, times out, or returns output that violates the byte cap.
Section-wise truncation keeps the most recent material: Facts is truncated
first, Done second, never Next. The git log lines become Done entries so
the next worker still knows what landed.
"""

from __future__ import annotations

from fleet.core.compaction import CompactionMaterial

STATE_MAX_BYTES = 6144

_DONE_BYTES_CAP = 600  # Done-section budget when folding git log entries in

_STATE_HEADINGS = ("Plan", "Done", "In flight", "Next", "Facts")


def _truncate(text: str, max_bytes: int) -> str:
    """Keep the first *max_bytes* bytes, dropping a trailing partial char."""
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    return encoded[:max_bytes].decode("utf-8", errors="ignore")


def _split_sections(text: str) -> dict[str, str]:
    """Split STATE.md *text* into its five sections (missing ones are "")."""
    sections: dict[str, str] = dict.fromkeys(_STATE_HEADINGS, "")
    current: str | None = None
    buckets: dict[str, list[str]] = {h: [] for h in _STATE_HEADINGS}
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            name = stripped[3:].strip()
            match = next((h for h in _STATE_HEADINGS if h.lower() == name.lower()), None)
            current = match
            continue
        if current is not None:
            buckets[current].append(line)
    for h in _STATE_HEADINGS:
        sections[h] = "\n".join(buckets[h]).strip()
    return sections


def _render(task_id: str, sections: dict[str, str]) -> str:
    parts = [f"# {task_id} — STATE (compacted fallback)", ""]
    for heading in _STATE_HEADINGS:
        parts.append(f"## {heading}")
        parts.append(sections[heading] or "(none recorded)")
        parts.append("")
    return "\n".join(parts).strip() + "\n"


def fallback_state(
    material: CompactionMaterial,
    task_id: str = "task",
    max_bytes: int = STATE_MAX_BYTES,
) -> str:
    """Build a bounded STATE.md from the current sections + git log as Done.

    Truncation order when over *max_bytes*: Facts first, Done second, then
    In flight, then Plan — never Next. Summaries and the last RESULT.json
    feed Done entries; the git log lines become Done entries so the next
    worker still knows what landed.
    """
    sections = _split_sections(material.state)

    done_lines = [line for line in sections["Done"].splitlines() if line.strip()]
    for commit in material.git_log[:30]:
        entry = f"- {commit}"
        if entry not in done_lines:
            done_lines.append(entry)
    if material.summaries:
        latest = material.summaries[-1].strip().splitlines()[:10]
        for raw_line in latest:
            line = raw_line.strip()
            if line and line not in done_lines and len("\n".join(done_lines)) < _DONE_BYTES_CAP:
                done_lines.append(f"- {line}" if not line.startswith("-") else line)
    if material.result_text.strip():
        first = material.result_text.strip().splitlines()[0][:200]
        entry = f"- last result: {first}"
        if entry not in done_lines:
            done_lines.append(entry)
    sections["Done"] = "\n".join(done_lines)

    text = _render(task_id, sections)
    if len(text.encode("utf-8")) <= max_bytes:
        return text

    # Shrink section by section; Next is never truncated.
    for heading in ("Facts", "Done", "In flight", "Plan"):
        while len(text.encode("utf-8")) > max_bytes and sections[heading]:
            body = sections[heading]
            sections[heading] = body[: len(body) // 2].strip()
            text = _render(task_id, sections)
        if len(text.encode("utf-8")) <= max_bytes:
            return text
    return _truncate(text, max_bytes)


def compact_fallback(
    material: CompactionMaterial,
    task_id: str = "task",
    max_bytes: int = STATE_MAX_BYTES,
) -> str:
    """Return the fallback STATE.md within its byte cap. Pure."""
    return fallback_state(material, task_id, max_bytes)
