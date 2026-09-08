"""Tests for the pure deterministic compaction fallback (no model, no I/O)."""
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


def test_state_within_cap() -> None:
    state = compact_fallback(_state(), ["summary line"], "", ["abc123 did the thing"])
    assert len(state.encode("utf-8")) <= STATE_MAX_BYTES
    assert "## Next" in state


def test_git_log_becomes_done_list() -> None:
    state = fallback_state(_state(Done=""), [], "", ["abc123 did the thing"])
    assert "abc123 did the thing" in state
    assert "## Done" in state
    assert "## Next" in state


def test_huge_inputs_still_bounded() -> None:
    state = compact_fallback(
        _state(Facts="K" * 40000, Done="H" * 20000),
        ["S" * 8000],
        '{"status": "partial"}',
        [f"commit-{i}" for i in range(50)],
    )
    assert len(state.encode("utf-8")) <= STATE_MAX_BYTES


def test_facts_truncated_first_next_never() -> None:
    """Over-cap input shrinks Facts (then Done) but keeps Next verbatim."""
    next_text = "- the one next step"
    state = fallback_state(
        _state(Facts="F" * 20000, Done="D" * 20000, Next=next_text),
        [],
        "",
        [],
        max_bytes=2000,
    )
    assert len(state.encode("utf-8")) <= 2000
    assert next_text in state


def test_empty_inputs_produce_skeleton() -> None:
    state = compact_fallback("", [], "", [])
    assert "## Done" in state
    assert "## Next" in state
    assert "## Facts" in state
    assert "## Plan" in state


def test_fallback_is_deterministic() -> None:
    args = (_state(), ["sum"], '{"status": "partial"}', ["abc log line"])
    assert compact_fallback(*args) == compact_fallback(*args)


def test_state_keeps_curated_facts() -> None:
    state = fallback_state(_state(), [], "", [])
    assert "fleet uses beads" in state
