"""R7 template recency dedupe (F7), voice notes (F8), length check (F14)."""

from __future__ import annotations

from tests.tweet_watch.r7.conftest import template_text


def test_template_states_three_day_dedupe_window() -> None:
    text = template_text()
    assert "3 days" in text or "three days" in text.lower(), (
        "template must instruct reading replies from the last 3 days and "
        "comparing before proposing (R7-F7)"
    )


def test_template_mentions_dedupe_check() -> None:
    lowered = template_text().lower()
    assert any(word in lowered for word in ("dedup", "near-identical", "duplicate"))


def test_template_fails_closed_without_dedupe_verdict() -> None:
    assert "fail closed" in template_text().lower(), (
        "no proposal without the dedupe verdict (R7-F7)"
    )


def test_template_points_to_interests_voice_notes() -> None:
    text = template_text()
    assert "INTERESTS.md" in text
    assert "voice" in text.lower(), (
        "template must point at the INTERESTS.md voice notes; drafts that "
        "cannot be voice-checked are not proposed (R7-F8)"
    )


def test_template_instructs_length_check_before_proposing() -> None:
    lowered = template_text().lower()
    assert "length" in lowered or "limit" in lowered or "280" in lowered, (
        "template must instruct rewrite/trim before proposing and forbid "
        "mid-word auto-truncation (R7-F14)"
    )
