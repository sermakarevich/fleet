"""R7 template HIGH-only proposal rule (F6), quiet runs (F12), cardinality (F13)."""

from __future__ import annotations

from tests.tweet_watch.r7.conftest import template_text


def test_template_states_high_only_gate() -> None:
    lowered = template_text().lower()
    assert "high-only" in lowered or "high only" in lowered


def test_template_names_all_three_labels() -> None:
    text = template_text()
    assert "HIGH" in text and "MEDIUM" in text and "LOW" in text, (
        "a template saying 'propose interesting tweets' without the "
        "HIGH/MEDIUM/LOW gate is a template bug (R7-F6)"
    )


def test_template_forbids_medium_low_proposals() -> None:
    lowered = template_text().lower()
    assert "never" in lowered, (
        "template must state MEDIUM/LOW never trigger a proposal (R7-F6)"
    )


def test_template_states_quiet_exit() -> None:
    text = template_text()
    lowered = text.lower()
    assert "ask_human" in text
    assert "zero" in lowered, (
        "template must state the quiet exit explicitly: zero ask_human "
        "calls, zero new files, successful run (R7-F12)"
    )


def test_template_forbids_batching_proposals() -> None:
    assert "batch" in template_text().lower(), (
        "template must forbid batching N HIGH tweets into one call and "
        "fanning one tweet into two calls (R7-F13)"
    )
