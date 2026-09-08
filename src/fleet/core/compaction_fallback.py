"""Deterministic compaction fallback: bounded HANDOFF.md + KNOWLEDGE.md without a model.

Pure: no I/O, no subprocess. Used by ``workers/compact.py`` when the cheap
model call fails, times out, or returns output that violates the byte caps.
Section-wise truncation keeps the most recent material; the git log lines
become the Done list so the next worker still knows what landed.
"""

from __future__ import annotations

HANDOFF_MAX_BYTES = 2000
KNOWLEDGE_MAX_BYTES = 4000


def _truncate(text: str, max_bytes: int) -> str:
    """Keep the first *max_bytes* bytes, dropping a trailing partial char."""
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    return encoded[:max_bytes].decode("utf-8", errors="ignore")


def _section(text: str, heading: str) -> str:
    """Return the markdown section under *heading* (exact `#`-level match)."""
    lines = text.splitlines()
    collecting = False
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#"):
            if collecting:
                break
            if stripped.lstrip("#").strip().lower() == heading.lower():
                collecting = True
            continue
        if collecting:
            out.append(line)
    return "\n".join(out).strip()


def fallback_handoff(
    handoff_text: str,
    summaries: list[str],
    git_log: list[str],
    max_bytes: int = HANDOFF_MAX_BYTES,
) -> str:
    """Build a bounded HANDOFF.md from existing sections + git log as Done."""
    done_src = _section(handoff_text, "Done") or _section(handoff_text, "done")
    flight = _section(handoff_text, "In flight") or _section(handoff_text, "in flight")
    nxt = _section(handoff_text, "Next") or _section(handoff_text, "next")
    no_redo = _section(handoff_text, "Do not redo") or _section(handoff_text, "do not redo")

    done_lines = [line for line in done_src.splitlines() if line.strip()]
    for commit in git_log[:30]:
        entry = f"- {commit}"
        if entry not in done_lines:
            done_lines.append(entry)
    if summaries:
        latest = summaries[-1].strip().splitlines()[:10]
        for line in latest:
            line = line.strip()
            if line and line not in done_lines and len("\n".join(done_lines)) < 600:
                done_lines.append(f"- {line}" if not line.startswith("-") else line)

    text = (
        "# HANDOFF (compacted fallback)\n\n"
        f"## Done\n{chr(10).join(done_lines) or '(unknown — see git log)'}\n\n"
        f"## In flight\n{flight or '(unknown)'}\n\n"
        f"## Next\n{nxt or '(continue from Next above)'}\n\n"
        f"## Do not redo\n{no_redo or '(none recorded)'}\n"
    )
    return _truncate(text, max_bytes)


def fallback_knowledge(
    knowledge_text: str,
    git_log: list[str],
    max_bytes: int = KNOWLEDGE_MAX_BYTES,
) -> str:
    """Build a bounded KNOWLEDGE.md from curated facts + recent commits."""
    facts = _section(knowledge_text, "Facts") or knowledge_text.strip()
    lines = [f"- {c}" for c in git_log[:30]]
    text = (
        "# KNOWLEDGE (compacted fallback)\n\n"
        "## Facts\n"
        f"{facts or '(no curated facts recorded)'}\n\n"
        "## Recent commits\n"
        f"{chr(10).join(lines) or '(none)'}\n"
    )
    return _truncate(text, max_bytes)


def compact_fallback(
    handoff_text: str,
    knowledge_text: str,
    summaries: list[str],
    git_log: list[str],
    handoff_max_bytes: int = HANDOFF_MAX_BYTES,
    knowledge_max_bytes: int = KNOWLEDGE_MAX_BYTES,
) -> tuple[str, str]:
    """Return ``(handoff, knowledge)`` within their byte caps. Pure."""
    return (
        fallback_handoff(handoff_text, summaries, git_log, handoff_max_bytes),
        fallback_knowledge(knowledge_text, git_log, knowledge_max_bytes),
    )
