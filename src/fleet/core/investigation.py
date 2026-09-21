"""Parse the blocked-task investigator's INVESTIGATION.md (pure: no I/O).

The bundled `blocked-task-investigator` trigger (docs/triggers/) opens one
bead per fleet-blocked task; its worker writes a markdown report with fixed
sections. This module turns that text into a typed record so the triage
question (core/triage_policy.py) can tell the operator WHY a task blocked
instead of offering a bare list of options.

Tolerant by design: a missing, reworded or half-written section yields an
empty string, never an exception — a partial report must still improve the
question.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

HEADLINE_MAX_CHARS = 200

_FIELDS: tuple[tuple[str, str], ...] = (
    ("root cause", "root_cause"),
    ("evidence", "evidence"),
    ("category", "category"),
    ("recommended action", "recommended_action"),
    ("confidence", "confidence"),
)
_ATTR_BY_LABEL = dict(_FIELDS)

_HEADING_RE = re.compile(r"^\s*#{1,6}\s+(.*?)\s*$")
_BULLET_RE = re.compile(r"^[-*]\s+(.*)$", re.DOTALL)
_WS_RE = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class InvestigationReport:
    """One parsed INVESTIGATION.md; every field defaults to ""."""

    root_cause: str = ""
    evidence: str = ""
    category: str = ""
    recommended_action: str = ""
    confidence: str = ""
    raw: str = ""

    @property
    def is_empty(self) -> bool:
        """True when no section carried any text."""
        return not (
            self.root_cause
            or self.evidence
            or self.category
            or self.recommended_action
            or self.confidence
        )

    def headline(self) -> str:
        """One plain-language sentence for the top of a triage question."""
        source = self.root_cause or _first_content_line(self.raw)
        text = _WS_RE.sub(" ", source).strip()
        pos = text.find(". ")
        sentence = text[: pos + 1] if pos != -1 else text
        if len(sentence) <= HEADLINE_MAX_CHARS:
            return sentence
        cut = sentence[:HEADLINE_MAX_CHARS]
        space = cut.rfind(" ")
        if space > 0:
            cut = cut[:space]
        return cut.rstrip() + "…"


def parse_report(text: str) -> InvestigationReport:
    """Parse report text; unknown or missing sections become ""."""
    if not isinstance(text, str):
        text = ""
    found = _parse_heading_form(text)
    found = _fill_label_form(text, found)
    return InvestigationReport(
        root_cause=found.get("root_cause", ""),
        evidence=found.get("evidence", ""),
        category=found.get("category", ""),
        recommended_action=found.get("recommended_action", ""),
        confidence=found.get("confidence", ""),
        raw=text,
    )


def _heading_text(line: str) -> str | None:
    """Raw text of a markdown heading line, else None."""
    match = _HEADING_RE.match(line)
    return None if match is None else match.group(1)


def _normalise_heading(text: str) -> str:
    """Lowercase heading text stripped of emphasis and a trailing colon."""
    name = text.strip()
    if name.endswith(":"):
        name = name[:-1]
    return name.strip().strip("*").strip().lower()


def _label_value(line: str, label: str) -> str | None:
    """Value after `<label>:` on one line, else None when it is no label line."""
    rest = line.strip()
    bullet = _BULLET_RE.match(rest)
    if bullet is not None:
        rest = bullet.group(1).strip()
    if rest.startswith("**"):
        rest = rest[2:].lstrip()
    if rest[: len(label)].lower() != label:
        return None
    rest = rest[len(label) :].lstrip()
    if rest.startswith("**"):
        rest = rest[2:].lstrip()
    if not rest.startswith(":"):
        return None
    rest = rest[1:].lstrip()
    if rest.startswith("**"):
        rest = rest[2:].lstrip()
    return rest


def _matches_any_label(line: str) -> bool:
    """True when the line opens any known label-form section."""
    return any(_label_value(line, label) is not None for label, _ in _FIELDS)


def _parse_heading_form(text: str) -> dict[str, str]:
    """Map attribute name to body for sections written as markdown headings."""
    found: dict[str, str] = {}
    current: str | None = None
    buf: list[str] = []
    for line in text.splitlines():
        heading = _heading_text(line)
        if heading is not None:
            if current is not None and current not in found:
                found[current] = "\n".join(buf).strip()
            current = _ATTR_BY_LABEL.get(_normalise_heading(heading))
            buf = []
        elif current is not None:
            buf.append(line)
    if current is not None and current not in found:
        found[current] = "\n".join(buf).strip()
    return found


def _fill_label_form(text: str, found: dict[str, str]) -> dict[str, str]:
    """Fill fields still empty from `- Label: value` bullet-style lines."""
    lines = text.splitlines()
    for label, attr in _FIELDS:
        if found.get(attr):
            continue
        for i, line in enumerate(lines):
            value = _label_value(line, label)
            if value is None:
                continue
            chunk = [value]
            for follow in lines[i + 1 :]:
                if not follow.strip():
                    break
                if _heading_text(follow) is not None:
                    break
                if _matches_any_label(follow):
                    break
                chunk.append(follow)
            found[attr] = "\n".join(chunk).strip()
            break
    return found


def _first_content_line(raw: str) -> str:
    """First non-empty raw line that is not a markdown heading."""
    for line in raw.splitlines():
        if line.strip() and _heading_text(line) is None:
            return line
    return ""
