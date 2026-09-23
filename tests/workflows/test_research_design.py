"""Tests for the research design contract (fleet-1r2mv).

Sources live in exactly one place — ``research_topics/<topic>/<Name>/``,
filed by each summarise run's file stage. The design phase therefore emits
no copy/move beads: fresh sources get one ``src-NN`` summarise child each
(with the topic passed through), already-in-the-KB sources are linked in
place, and the aggregation pages point at the topic folder.
"""

from __future__ import annotations

from pathlib import Path

from fleet.workers.research_bodies import KINDS

_TEMPLATES = Path(__file__).resolve().parent.parent.parent / "src" / "fleet" / "templates"


def _read(name: str) -> str:
    return (_TEMPLATES / name).read_text(encoding="utf-8")


def test_design_has_no_copy_step() -> None:
    """The copy bead is gone: no copy-NN key, no copy template reference."""
    text = _read("INSTRUCTION_RESEARCH_DESIGN.md")
    assert "copy-NN" not in text
    assert "copy-01" not in text
    assert "research/copy.md" not in text
    assert not (_TEMPLATES / "research" / "copy.md").exists()
    assert "copy" not in KINDS


def test_design_passes_topic_to_every_summarise_child() -> None:
    """Each src-NN child carries url + research_target + topic inputs."""
    text = _read("INSTRUCTION_RESEARCH_DESIGN.md")
    assert '"topic": "<TOPIC>"' in text
    assert '"research_target": "<TARGET>"' in text
    assert '"workflow": "summarise"' in text


def test_design_links_in_kb_sources_instead_of_resummarising() -> None:
    """in_kb shortlist entries produce no task; topic digests link their origin."""
    text = _read("INSTRUCTION_RESEARCH_DESIGN.md")
    assert "No task at all" in text
    assert "{{linked}}" in text


def test_topic_pages_point_at_research_topics() -> None:
    """topic-NN and aggregate pages read/link sources under research_topics/."""
    assert "research_topics/" in _read("research/topic_digest.md")
    assert "research_topics/" in _read("research/agg_disagreements.md")
    assert "research_topics/" in _read("research/agg_index.md")
    assert "research_topics/" in _read("research/lens.md")


def test_agg_index_owns_the_sources_ledger() -> None:
    """With no copy beads, agg-index writes the sources.md rows from candidates.json."""
    text = _read("research/agg_index.md")
    assert "sources.md" in text
    assert "candidates.json" in text
    assert "status=processed" in text
    assert "status=in_kb" in text


def test_discover_scans_research_topics_for_dedup() -> None:
    """The already-in-KB check covers topic entries (index front-matter + summary)."""
    text = _read("INSTRUCTION_RESEARCH_DISCOVER.md")
    assert "research_topics/*/*/index.md" in text
    assert "research_topics/*/*/summary.md" in text
    assert "for linking later" in text


def test_discover_requires_topic() -> None:
    """The bead description carries the topic so discover/design phases see it."""
    text = _read("INSTRUCTION_RESEARCH_DISCOVER.md")
    assert "| `topic` | yes |" in text
