"""R7 template step order (F11), drift rule (F15), mid-run snapshot (F22)."""

from __future__ import annotations

from tests.tweet_watch.r7.conftest import template_text


def test_template_lists_r1_through_r6_in_order() -> None:
    text = template_text()
    positions = [text.index(f"R{i}") for i in range(1, 7)]
    assert positions == sorted(positions), (
        "R1->R6 order binds regardless of document order (R7-F11)"
    )


def test_template_states_requirements_win_over_stale_copy() -> None:
    lowered = template_text().lower()
    assert "requirement" in lowered or "REQUIREMENTS" in template_text()
    assert any(word in lowered for word in ("wins", "mismatch", "stale", "drift")), (
        "the numbered requirement wins over the template copy (R7-F15)"
    )


def test_template_instructs_working_r1_snapshot() -> None:
    assert "snapshot" in template_text().lower(), (
        "template must instruct working the R1 snapshot for the run when "
        "the watchlist is edited mid-run (R7-F22)"
    )
