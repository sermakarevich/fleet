"""Render child-bead bodies for research runs (ADR 0015 §4, §6).

Each child body lives in ``templates/research/<kind>.md`` with
``{{placeholder}}`` tokens; the design phase fills them (one filled body per
child bead) so every research run's children carry identical, tested text.
Line 1 of each template is an HTML comment listing its placeholders.

Spawn-time fix (ADR 0015 amendment 2026-09-23): when a ``src-NN`` workflow
child is skipped, :func:`strip_names_from_lists` removes its guessed folder
name from the space-separated source lists in already-rendered dependent
bodies, and :func:`build_sources_note` appends the authoritative
per-source table (key, title, guessed folder, url, status) those bodies
point at. :func:`resolve_folder` is the same folder-resolution procedure
the topic-digest template tells its worker to follow (``Source:``
provenance scan, guessed-folder fallback).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

KINDS = (
    "topic_digest",
    "agg_digest",
    "agg_overview",
    "agg_agreements",
    "agg_disagreements",
    "agg_open_questions",
    "lens",
    "agg_index",
)

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates" / "research"

_PLACEHOLDER_RE = re.compile(r"\{\{([A-Za-z0-9_]+)\}\}")


def render_body(kind: str, **fields: str) -> str:
    """Fill ``templates/research/<kind>.md`` with *fields*.

    Every ``{{name}}`` token is replaced by ``fields["name"]``. Raises
    :class:`KeyError` naming the first unfilled placeholder (in file order)
    when a field is missing.
    """
    text = (_TEMPLATES_DIR / f"{kind}.md").read_text(encoding="utf-8")
    names = _PLACEHOLDER_RE.findall(text)
    for name in names:
        if name not in fields:
            raise KeyError(f"missing placeholder for render_body({kind!r}): {name!r}")
    return _PLACEHOLDER_RE.sub(lambda m: fields[m.group(1)], text)


#: Marker opening the spawn-appended source-resolution section. Workers
#: (and the topic-digest template) treat this section as authoritative
#: over the design-time source lists above it.
SOURCES_NOTE_HEADER = "## Source resolution (added at spawn; authoritative)"

#: Replacement for a backticked source list left empty after skipped names
#: are stripped: points the worker at the note instead of an empty read set.
SOURCES_LIST_EMPTIED = "`(none — every source skipped; see Source resolution below)`"

_BACKTICK_SPAN_RE = re.compile(r"`([^`\n]+)`")


@dataclass
class SourceRow:
    """One depended-on source for the spawn appendix and manifest."""

    key: str
    title: str
    folder: str | None  # design-time guessed <Name>; None when unrecorded
    url: str
    status: str  # "ready (run ...)" | "skipped: <reason>" | "deferred: <reason>"
    skipped: bool = False


def strip_names_from_lists(body: str, names: set[str]) -> tuple[str, set[str]]:
    """Remove *names* from backticked whitespace-separated lists in *body*.

    Only whole whitespace-separated items equal to a skipped name are
    dropped, so ``Foo`` never matches ``FooBar`` and path spans such as
    ```research_topics/t/<Name>/summary.md``` (one item containing slashes)
    are untouched. A span left empty becomes :data:`SOURCES_LIST_EMPTIED`.
    Returns the new body and the subset of *names* actually removed.
    """
    if not names:
        return body, set()
    removed: set[str] = set()

    def _fix(match: re.Match[str]) -> str:
        items = match.group(1).split()
        kept = [item for item in items if item.strip(",;") not in names]
        if len(kept) == len(items):
            return match.group(0)
        removed.update(
            item.strip(",;") for item in items if item.strip(",;") in names
        )
        if not kept:
            return SOURCES_LIST_EMPTIED
        return "`" + " ".join(kept) + "`"

    return _BACKTICK_SPAN_RE.sub(_fix, body), removed


def build_sources_note(rows: list[SourceRow], manifest_path: str) -> str:
    """Render the spawn appendix: one row per depended-on workflow source."""
    lines = [
        SOURCES_NOTE_HEADER,
        "",
        "The design-time source lists above may name skipped sources or "
        "guessed folder names. This table (same data as the manifest) wins: "
        f"re-read {manifest_path} at claim time, it may be newer than this note.",
        "",
        "| key | title | folder (design guess — verify on disk) | source url | status |",
        "|---|---|---|---|---|",
    ]
    for row in rows:
        folder = row.folder or "(unrecorded)"
        lines.append(f"| {row.key} | {row.title} | {folder} | {row.url} | {row.status} |")
    return "\n".join(lines) + "\n"


def resolve_folder(topic_dir: Path, url: str | None, guess: str | None) -> str | None:
    """Resolve a source's real filed folder name under *topic_dir*.

    A summarise run files its entry as ``research_topics/<topic>/<Name>/``
    where ``<Name>`` is the plan step's own slug, which may differ from the
    design-time guess. The entry's ``source/source.md`` carries a ``Source:``
    provenance line with the exact input url, so an exact url match wins;
    otherwise a ``summary.md`` containing the url is accepted. When nothing
    matches, the guess is kept only if that folder exists, else None (the
    caller reports the source unreachable — never pending).
    """
    if url:
        for source_md in sorted(topic_dir.glob("*/source/source.md")):
            try:
                for line in source_md.read_text(encoding="utf-8").splitlines():
                    if line.strip() == f"Source: {url}":
                        return source_md.parent.parent.name
            except OSError:
                continue
        for summary_md in sorted(topic_dir.glob("*/summary.md")):
            try:
                if url in summary_md.read_text(encoding="utf-8"):
                    return summary_md.parent.name
            except OSError:
                continue
    if guess and (topic_dir / guess).is_dir():
        return guess
    return None
