"""Tests for the pure deterministic compaction fallback (no model, no I/O)."""
from fleet.core.compaction_fallback import (
    HANDOFF_MAX_BYTES,
    KNOWLEDGE_MAX_BYTES,
    compact_fallback,
    fallback_handoff,
    fallback_knowledge,
)


def test_handoff_within_cap() -> None:
    handoff, _ = compact_fallback(
        "# H\n\n## Done\n- a\n\n## In flight\n- b\n\n## Next\n- c\n\n## Do not redo\n- d\n",
        "facts",
        ["summary line"],
        ["abc123 did the thing"],
    )
    assert len(handoff.encode("utf-8")) <= HANDOFF_MAX_BYTES


def test_knowledge_within_cap() -> None:
    _, knowledge = compact_fallback("h", "x" * 9000, [], ["abc123 did the thing"])
    assert len(knowledge.encode("utf-8")) <= KNOWLEDGE_MAX_BYTES


def test_git_log_becomes_done_list() -> None:
    handoff = fallback_handoff("", [], ["abc123 did the thing", "def456 another"])
    assert "abc123 did the thing" in handoff
    assert "## Done" in handoff
    assert "## Next" in handoff


def test_huge_inputs_still_bounded() -> None:
    handoff, knowledge = compact_fallback(
        "H" * 20000, "K" * 40000, ["S" * 8000], [f"commit-{i}" for i in range(50)]
    )
    assert len(handoff.encode("utf-8")) <= HANDOFF_MAX_BYTES
    assert len(knowledge.encode("utf-8")) <= KNOWLEDGE_MAX_BYTES


def test_empty_inputs_produce_skeleton() -> None:
    handoff, knowledge = compact_fallback("", "", [], [])
    assert "## Done" in handoff
    assert "## Do not redo" in handoff
    assert "## Facts" in knowledge


def test_fallback_is_deterministic() -> None:
    args = ("handoff text", "knowledge text", ["sum"], ["abc log line"])
    assert compact_fallback(*args) == compact_fallback(*args)


def test_knowledge_keeps_curated_facts() -> None:
    knowledge = fallback_knowledge("## Facts\n- fleet uses beads\n", [])
    assert "fleet uses beads" in knowledge
