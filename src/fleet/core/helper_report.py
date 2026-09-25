"""Parse a helper worker's HELPER_REPORT.md (pure: no I/O).

The blocked-task helper (docs/design/blocked-task-helper.md,
templates/HELPER_INVESTIGATE.md) writes a markdown report with fixed
sections into its own task directory. This module turns that text into a
typed record so the orchestrator's progress check can tell whether a
helper's root cause repeats an earlier one in the same chain.

Tolerant by design: a missing, reworded or half-written section yields an
empty string (or None for same_as_previous), never an exception.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_FIELDS: tuple[tuple[str, str], ...] = (
    ("root cause", "root_cause"),
    ("evidence", "evidence"),
    ("same as previous root cause", "same_as_previous"),
    ("proposed fixes", "proposed_fixes"),
)
_ATTR_BY_LABEL = dict(_FIELDS)

_HEADING_RE = re.compile(r"^\s*#{1,6}\s+(.*?)\s*$")
_BULLET_RE = re.compile(r"^[-*]\s+(.*)$", re.DOTALL)


@dataclass(frozen=True, slots=True)
class HelperReport:
    """One parsed HELPER_REPORT.md; every field defaults to ""."""

    root_cause: str = ""
    evidence: str = ""
    same_as_previous: bool | None = None
    proposed_fixes: str = ""
    raw: str = ""


def parse_report(text: str) -> HelperReport:
    """Parse report text; unknown or missing sections become defaults."""
    if not isinstance(text, str):
        text = ""
    found = _parse_heading_form(text)
    found = _fill_label_form(text, found)
    return HelperReport(
        root_cause=found.get("root_cause", ""),
        evidence=found.get("evidence", ""),
        same_as_previous=_parse_bool(found.get("same_as_previous")),
        proposed_fixes=found.get("proposed_fixes", ""),
        raw=text,
    )


def _parse_bool(value: str | None) -> bool | None:
    """First word of `value` as yes/no, else None when unparsable or absent."""
    if not value:
        return None
    word = re.split(r"\W+", value.strip(), maxsplit=1)[0].lower()
    if word == "yes":
        return True
    if word == "no":
        return False
    return None


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
