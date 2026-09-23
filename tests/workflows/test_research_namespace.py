"""Tests for the research/ entry-vs-epic namespace guards (fleet-wr1e1).

`knowledge/research/` holds summarise ENTRY folders (`<PascalSlug>/` with
`source/source.md`) and may hold research-epic hubs (`<target>/` with a
`sources/` subdirectory and `type: Research` hub index). These tests pin the
worker instructions that keep the two apart.
"""

from __future__ import annotations

from pathlib import Path

from fleet.workflows.builders import summarise

_TEMPLATES = Path(__file__).resolve().parent.parent.parent / "src" / "fleet" / "templates"


def _read(name: str) -> str:
    return (_TEMPLATES / name).read_text(encoding="utf-8")


def test_discover_skips_epic_hubs() -> None:
    """The already-in-KB check must skip epic hubs for the top-level glob."""
    text = _read("INSTRUCTION_RESEARCH_DISCOVER.md")
    assert "type: Research" in text
    assert "sources/" in text
    assert "source/source.md" in text


def test_plan_never_reuses_epic_hub() -> None:
    """The plan step must treat an epic-hub collision as conflict, never reuse."""
    assert "Epic-hub rule" in summarise._PLAN_DESC
    assert "NEVER" in summarise._PLAN_DESC
    assert "type: Research" in summarise._PLAN_DESC


def test_copy_skips_epic_hubs() -> None:
    """The copy locate step must skip epic hubs while scanning for origins."""
    text = _read("research/copy.md")
    assert "type: Research" in text
    assert "source/source.md" in text
