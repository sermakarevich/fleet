"""Tests for the research design contract (fleet-1r2mv).

Sources live in exactly one place — ``research_topics/<topic>/<Name>/``,
filed by each summarise run's file stage. The design phase therefore emits
no copy/move beads: fresh sources get one ``src-NN`` summarise child each
(with the topic passed through), already-in-the-KB sources are linked in
place, and the aggregation pages point at the topic folder.
"""

from __future__ import annotations

from pathlib import Path

from fleet.workers.research_bodies import KINDS, render_body

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


def test_design_emits_agreements_next_to_disagreements() -> None:
    """agg-agreements is a topic-level bead and agg-index waits for it."""
    text = _read("INSTRUCTION_RESEARCH_DESIGN.md")
    assert '"key": "agg-agreements"' in text
    assert '"agg-agreements", "agg-disagreements"' in text
    assert "agreements.md" in _read("research/agg_agreements.md")
    assert "agreements.md" in _read("research/agg_overview.md")


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


def test_design_target_lives_under_topic() -> None:
    """TARGET is research_topics/<topic>/research/<target>, not knowledge/research/<target>."""
    text = _read("INSTRUCTION_RESEARCH_DESIGN.md")
    assert "research_topics/<TOPIC>/research/<target>" in text
    assert "knowledge/research/<target>" not in text


def test_discover_target_row_points_under_topic() -> None:
    """The target input is a slug under research_topics/<topic>/research/."""
    text = _read("INSTRUCTION_RESEARCH_DISCOVER.md")
    assert "research_topics/<topic>/research/" in text


def test_discover_dedup_covers_new_and_old_aggregates() -> None:
    """The already-in-KB scan covers new topic-nested research folders and old ones."""
    text = _read("INSTRUCTION_RESEARCH_DISCOVER.md")
    assert "research_topics/*/research/*/index.md" in text
    assert "/Users/sergii/.ai/knowledge/research/*/index.md" in text


def test_agg_index_registers_in_topic_page() -> None:
    """agg-index registers under ## Research in the topic page, not research/index.md."""
    target = "/Users/sergii/.ai/knowledge/research_topics/agent_memory/research/demo"
    body = render_body(
        "agg_index",
        target=target,
        topic="agent_memory",
        focus="How do agents remember?",
        lenses="tech ai",
        topics="memory-types retrieval",
    )
    assert "{{" not in body
    assert "research_topics/agent_memory/research/demo" in body
    assert "knowledge/research/demo" not in body
    assert "knowledge/research/index.md" not in body
    assert "## Research" in body
    assert "## Tutorials" in body
    assert "research/<slug>/index|<slug>" in body
