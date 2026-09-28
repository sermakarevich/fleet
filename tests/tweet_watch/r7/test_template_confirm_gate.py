"""R7 template confirmation gate (F9) and id-less confirmations (F25)."""

from __future__ import annotations

from tests.tweet_watch.r7.conftest import template_text


def test_template_requires_confirmation_before_storing() -> None:
    lowered = template_text().lower()
    assert "confirm" in lowered
    assert "only" in lowered or "unconfirmed" in lowered, "unconfirmed drafts store nothing (R7-F9)"


def test_template_names_reply_filename_pattern() -> None:
    assert "<date>-<id>.md" in template_text(), (
        "reply files <date>-<id>.md only on confirmation (R7-F9)"
    )


def test_template_states_unconfirmed_drafts_store_nothing() -> None:
    lowered = template_text().lower()
    assert "unconfirmed" in lowered and "nothing" in lowered


def test_template_requires_reply_id_for_filename() -> None:
    lowered = template_text().lower()
    assert any(
        phrase in lowered for phrase in ("reply id", "reply_id", "tweet id", "post id", "posted id")
    ), "a confirmation without a reply id stores nothing (R7-F25)"
