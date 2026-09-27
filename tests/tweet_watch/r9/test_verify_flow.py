"""R9 verify flow: one manual run executes R1-R6 exactly once.

Covers the R9 observable plus F9 (quiet watch succeeds with zero calls),
F10 (backlog emits everything, one proposal per HIGH), F12 (second manual
run is quiet), and the R5 quiet rule (MEDIUM/LOW never proposed).
"""

from __future__ import annotations

import json

from .conftest import (
    LOW_TEXT,
    TODAY,
    AskLog,
    canned_fetch,
    make_tweet,
    run_or_fail_scaffold,
    write_interests,
    write_watchlist,
)


def test_manual_run_executes_r1_to_r6_once(kb, monkeypatch) -> None:
    write_watchlist(kb, ["typesafeai"])
    write_interests(kb)
    canned_fetch(monkeypatch, [make_tweet()])
    ask = AskLog(answers=["posted https://x.com/i/status/555"])
    assert run_or_fail_scaffold(ask=ask, today=TODAY, recent_texts=[]) is None
    assert len(ask.messages) == 1
    assert "https://x.com/typesafeai/status/300" in ask.messages[0]
    assert len(ask.messages[0]) > len("https://x.com/typesafeai/status/300")
    reply_file = kb.replies / "2026-09-26-555.md"
    assert reply_file.is_file()
    assert "> source:" in reply_file.read_text(encoding="utf-8")
    assert json.loads(kb.state.read_text(encoding="utf-8")) == {"typesafeai": "300"}


def test_quiet_watch_succeeds_with_zero_calls(kb, monkeypatch) -> None:
    write_watchlist(kb, ["typesafeai"])
    write_interests(kb)
    canned_fetch(monkeypatch, [])
    ask = AskLog()
    assert run_or_fail_scaffold(ask=ask, today=TODAY, recent_texts=[]) is None
    assert ask.messages == []
    assert list(kb.replies.iterdir()) == []


def test_zero_high_tweets_means_zero_calls(kb, monkeypatch) -> None:
    write_watchlist(kb, ["typesafeai"])
    write_interests(kb)
    canned_fetch(monkeypatch, [make_tweet(tweet_id="301", text=LOW_TEXT)])
    ask = AskLog()
    assert run_or_fail_scaffold(ask=ask, today=TODAY, recent_texts=[]) is None
    assert ask.messages == []
    assert list(kb.replies.iterdir()) == []


def test_backlog_emits_everything_since_last_id(kb, monkeypatch) -> None:
    write_watchlist(kb, ["typesafeai"])
    write_interests(kb)
    kb.state.write_text(json.dumps({"typesafeai": "100"}), encoding="utf-8")
    backlog = [
        make_tweet(
            "101",
            text=(
                "Checkout queue experiments cut flaky reruns 40%: "
                "a verifier model now screens each coding agent patch."
            ),
        ),
        make_tweet(
            "102",
            text=(
                "Dialog pacing trials lowered awkward pauses 200ms: "
                "a voice agent loop now batches replies smarter, "
                "checked by a verifier pass."
            ),
        ),
        make_tweet(
            "103",
            text=(
                "Invoice audits exposed idle spend 60%: "
                "cost engineering reviews now trim each coding agent call."
            ),
        ),
    ]
    canned_fetch(monkeypatch, backlog)
    ask = AskLog()
    run_or_fail_scaffold(ask=ask, today=TODAY, recent_texts=[])
    assert len(ask.messages) == 3
    for tweet_id, message in zip((101, 102, 103), ask.messages, strict=False):
        assert f"https://x.com/typesafeai/status/{tweet_id}" in message


def test_second_manual_run_is_quiet(kb, monkeypatch) -> None:
    write_watchlist(kb, ["typesafeai"])
    write_interests(kb)
    canned_fetch(monkeypatch, [make_tweet()])
    ask = AskLog()
    run_or_fail_scaffold(ask=ask, today=TODAY, recent_texts=[])
    assert len(ask.messages) == 1
    run_or_fail_scaffold(ask=ask, today=TODAY, recent_texts=[])
    assert len(ask.messages) == 1


def test_medium_low_tweets_never_proposed(kb, monkeypatch) -> None:
    write_watchlist(kb, ["typesafeai"])
    write_interests(kb)
    canned_fetch(
        monkeypatch,
        [make_tweet(tweet_id="300"), make_tweet(tweet_id="301", text=LOW_TEXT)],
    )
    ask = AskLog()
    run_or_fail_scaffold(ask=ask, today=TODAY, recent_texts=[])
    assert len(ask.messages) == 1
    assert "https://x.com/typesafeai/status/300" in ask.messages[0]
