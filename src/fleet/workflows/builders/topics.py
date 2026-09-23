"""Shared `research_topics/` helpers for the research and summarise builders.

A *topic* is a folder name under ``~/.ai/knowledge/research_topics/`` (one
folder per category, holding summarised entries plus ``<topic>.md``). Both
builders validate topic input through :func:`validate_topic` so research
fails fast on a typo instead of filing into a void.
"""

from __future__ import annotations

import re
from pathlib import Path

#: Files in research_topics/ that are not topics (vault indexes, not folders).
_NON_TOPIC_NAMES = frozenset({"index.md", "tutorials.md"})

_SNAKE_CASE_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def research_topics_dir() -> Path:
    """Absolute path of the ``research_topics/`` vault folder."""
    return Path.home() / ".ai" / "knowledge" / "research_topics"


def existing_topics() -> list[str]:
    """Sorted names of the topic folders on disk (empty when unreadable)."""
    base = research_topics_dir()
    try:
        entries = [p for p in base.iterdir() if p.is_dir() and p.name not in _NON_TOPIC_NAMES]
    except OSError:
        return []
    return sorted(p.name for p in entries)


def validate_topic(value: str | None) -> str:
    """Return the stripped topic or raise ValueError naming what is wrong.

    The topic must be snake_case and match an existing folder under
    ``research_topics/``. The error lists the existing topics and points at
    ``ai new <topic>`` so the operator can create one. ``research_topics_dir``
    is called (not inlined) so tests can monkeypatch it.
    """
    topic = (value or "").strip()
    if not topic:
        raise ValueError("input topic is required")
    if not _SNAKE_CASE_RE.match(topic):
        raise ValueError(
            f"input topic {topic!r} must be snake_case (lowercase letters, digits, underscores)"
        )
    if not (research_topics_dir() / topic).is_dir():
        known = existing_topics()
        known_str = ", ".join(known) if known else "none found on disk"
        raise ValueError(
            f"input topic {topic!r} does not exist under research_topics/ "
            f"(existing topics: {known_str}); create one with `ai new {topic}`"
        )
    return topic
