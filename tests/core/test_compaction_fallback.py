"""Tests for the pure deterministic compaction fallback (no model, no I/O)."""

from fleet.core.compaction import CompactionMaterial
from fleet.core.compaction_fallback import (
    STATE_MAX_BYTES,
    compact_fallback,
    fallback_state,
)


def _state(**overrides: str) -> str:
    sections = {
        "Plan": "do the thing",
        "Done": "- did a",
        "In flight": "- doing b",
        "Next": "- do c",
        "Facts": "- fleet uses beads",
    }
    sections.update(overrides)
    parts = ["# t — STATE", ""]
    for heading in ("Plan", "Done", "In flight", "Next", "Facts"):
        parts.append(f"## {heading}")
        parts.append(sections[heading])
        parts.append("")
    return "\n".join(parts)


def _material(state_text: str, **overrides) -> CompactionMaterial:
    return CompactionMaterial(state=state_text, **overrides)


def test_state_within_cap() -> None:
    material = _material(_state(), summaries=["summary line"], git_log=["abc123 did the thing"])
    state = compact_fallback(material)
    assert len(state.encode("utf-8")) <= STATE_MAX_BYTES
    assert "## Next" in state


def test_git_log_becomes_done_list() -> None:
    material = _material(_state(Done=""), git_log=["abc123 did the thing"])
    state = fallback_state(material)
    assert "abc123 did the thing" in state
    assert "## Done" in state
    assert "## Next" in state


def test_huge_inputs_still_bounded() -> None:
    material = _material(
        _state(Facts="K" * 40000, Done="H" * 20000),
        summaries=["S" * 8000],
        result_text='{"status": "partial"}',
        git_log=[f"commit-{i}" for i in range(50)],
    )
    state = compact_fallback(material)
    assert len(state.encode("utf-8")) <= STATE_MAX_BYTES


def test_facts_truncated_first_next_never() -> None:
    """Over-cap input shrinks Facts (then Done) but keeps Next verbatim."""
    next_text = "- the one next step"
    material = _material(_state(Facts="F" * 20000, Done="D" * 20000, Next=next_text))
    state = fallback_state(material, max_bytes=2000)
    assert len(state.encode("utf-8")) <= 2000
    assert next_text in state


def test_empty_inputs_produce_skeleton() -> None:
    state = compact_fallback(CompactionMaterial())
    assert "## Done" in state
    assert "## Next" in state
    assert "## Facts" in state
    assert "## Plan" in state


def test_fallback_is_deterministic() -> None:
    material = _material(
        _state(), summaries=["sum"], result_text='{"status": "partial"}', git_log=["abc log line"]
    )
    assert compact_fallback(material) == compact_fallback(
        _material(
            _state(),
            summaries=["sum"],
            result_text='{"status": "partial"}',
            git_log=["abc log line"],
        )
    )


def test_state_keeps_curated_facts() -> None:
    state = fallback_state(_material(_state()))
    assert "fleet uses beads" in state
