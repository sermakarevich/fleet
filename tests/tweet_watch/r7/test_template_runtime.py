"""R7 template runtime errors: INTERESTS (F17), ask_human (F18), schedule (F20),
deleted source (F23), outside reply (F24)."""

from __future__ import annotations

from tests.tweet_watch.r7.conftest import template_text


def test_template_aborts_proposals_when_interests_missing() -> None:
    lowered = template_text().lower()
    assert "missing" in lowered
    assert any(word in lowered for word in ("abort", "stop", "error")), (
        "without INTERESTS.md the run aborts proposals, never scores by gut feel (R7-F17)"
    )


def test_template_continues_batch_on_ask_human_failure() -> None:
    lowered = template_text().lower()
    assert "continu" in lowered or "remain" in lowered, (
        "template must instruct recording the tweet as unproposed and "
        "continuing with the remaining HIGH tweets (R7-F18)"
    )


def test_template_covers_single_pass_no_schedule_reinstall() -> None:
    lowered = template_text().lower()
    assert any(
        phrase in lowered for phrase in ("one pass", "single pass", "exactly once", "exactly one")
    ), "the template covers one run R1->R6, not the schedule (R7-F20)"


def test_template_notes_deleted_source_tweet() -> None:
    text = template_text()
    assert "delet" in text.lower() or "404" in text, (
        "propose once with cached text plus a dead-link note (R7-F23)"
    )


def test_template_states_manual_reply_still_proposes() -> None:
    lowered = template_text().lower()
    assert any(phrase in lowered for phrase in ("manual", "outside", "already replied")), (
        "an outside reply still proposes; no invented liveness check (R7-F24)"
    )
