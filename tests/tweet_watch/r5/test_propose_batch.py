"""R5 batch semantics through worker.run (proposal counts and gates).

The R5 observable is batch-level: N new HIGH tweets -> N proposals, each
with its own link + draft; zero HIGH -> zero calls. Dependencies outside
R5 (R1/R2/R3/R4/R6 steps) are monkeypatched; compose_draft and
propose_tweet under test are always the real objects.

Covers F7 (HIGH-only gate re-checked), F8 (no voice notes -> abort),
F10 (silence is correct), F11 (one call per tweet), F13 (dup id -> once),
batch-F15 (tool failure mid-batch continues), F20 (no R4 verdict -> closed),
F21/F22 (snapshot input still proposed), F23 (no locking), F24 (per-tweet
confirmations), F25 (no cross-run coordination in R5).
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

import fleet.tweet_watch.worker as worker_mod
from fleet.tweet_watch.worker import propose_tweet, run

from .conftest import GOOD_DRAFT, TODAY, AskRecorder, make_tweet


def _stub_run_deps(monkeypatch, tweets, score="HIGH", duplicate=False):
    """Wire run() seams: stub R1/R2/R3/R4/R6 steps, keep R5 real."""
    persisted: list[dict] = []
    monkeypatch.setattr(worker_mod, "ensure_watchlist", lambda watchlist_path=None: ["omarsar0"])

    def fake_find(handles, state_path=None, run_command=None):
        return list(tweets)

    monkeypatch.setattr(worker_mod, "find_new_tweets", fake_find)

    def fake_score(tweet_text, interests_text):
        return score

    monkeypatch.setattr(worker_mod, "score_tweet", fake_score)

    def fake_dupe(draft_text, recent_texts):
        if duplicate == "raise":
            raise OSError("replies dir unreadable (simulated)")
        return duplicate

    monkeypatch.setattr(worker_mod, "is_duplicate", fake_dupe)
    monkeypatch.setattr(worker_mod, "parse_confirmation", lambda answer_text, today: None)

    def fake_persist(source_url, source_body, posted_text, reply_id, post_date, replies_dir=None):
        persisted.append({"reply_id": reply_id, "post_date": post_date})
        return Path(f"{post_date}-{reply_id}.md")

    monkeypatch.setattr(worker_mod, "persist_reply", fake_persist)
    return persisted


def _quiet_run(ask, interests_text):
    run(ask=ask, today=TODAY, interests_text=interests_text, recent_texts=[])


def test_no_new_tweets_zero_calls_success(monkeypatch, interests_text: str) -> None:
    """F10: silence is the correct output, not an error."""
    _stub_run_deps(monkeypatch, [])
    ask = AskRecorder()
    _quiet_run(ask, interests_text)
    assert ask.prompts == []


@pytest.mark.parametrize("label", ["MEDIUM", "LOW"])
def test_medium_low_never_proposed(monkeypatch, interests_text: str, label: str) -> None:
    """F7: the HIGH-only gate is re-checked; upstream mis-scores stop here."""
    _stub_run_deps(monkeypatch, [make_tweet()], score=label)
    ask = AskRecorder()
    _quiet_run(ask, interests_text)
    assert ask.prompts == []


def test_three_high_tweets_three_calls_each_with_own_link(monkeypatch, interests_text: str) -> None:
    """F11: never batched into one call, never fanned out."""
    tweets = [
        make_tweet(id=f"196812345678901234{i}", url=f"https://x.com/u/status/{i}") for i in range(3)
    ]
    _stub_run_deps(monkeypatch, tweets)
    ask = AskRecorder(answers=["skip", "skip", "skip"])
    _quiet_run(ask, interests_text)
    assert len(ask.prompts) == 3
    for tweet, prompt in zip(tweets, ask.prompts, strict=False):
        assert tweet.url in prompt


def test_duplicate_id_in_batch_proposed_once(monkeypatch, interests_text: str) -> None:
    """F13: same id under two handles (quote-tweet) -> one proposal."""
    first = make_tweet(handle="omarsar0")
    second = make_tweet(handle="typesafeai")
    assert first.id == second.id and first.handle != second.handle
    _stub_run_deps(monkeypatch, [first, second])
    ask = AskRecorder(answers=["skip"])
    _quiet_run(ask, interests_text)
    assert len(ask.prompts) == 1
    assert first.url in ask.prompts[0]


def test_unreadable_recency_check_fails_closed(monkeypatch, interests_text: str) -> None:
    """F20: no dedupe verdict means no proposal (never propose blind)."""
    _stub_run_deps(monkeypatch, [make_tweet()], duplicate="raise")
    ask = AskRecorder()
    try:
        _quiet_run(ask, interests_text)
    except NotImplementedError:
        raise
    except Exception:
        pass
    assert ask.prompts == []


def test_missing_interests_aborts_proposals_with_error(monkeypatch, tmp_path: Path) -> None:
    """F8: drafts that cannot be voice-checked are never proposed."""
    _stub_run_deps(monkeypatch, [make_tweet()])
    monkeypatch.setattr(worker_mod, "INTERESTS_PATH", tmp_path / "nope" / "INTERESTS.md")
    ask = AskRecorder()
    with pytest.raises(Exception) as excinfo:
        run(ask=ask, today=TODAY, interests_text=None, recent_texts=[])
    assert not isinstance(excinfo.value, NotImplementedError)
    assert ask.prompts == []


def test_tool_failure_mid_batch_continues(monkeypatch, interests_text: str) -> None:
    """F15: the failed tweet is unproposed; the rest still go out."""
    tweets = [
        make_tweet(id="1968123456789012341", url="https://x.com/u/status/1"),
        make_tweet(id="1968123456789012342", url="https://x.com/u/status/2"),
    ]
    _stub_run_deps(monkeypatch, tweets)
    ask = AskRecorder(answers=["skip", "skip"])
    ask.fail_on = {0}
    try:
        _quiet_run(ask, interests_text)
    except NotImplementedError:
        raise
    except Exception:
        pass  # run exits non-zero OR logs loudly; continuation is the point
    assert len(ask.prompts) == 2
    assert tweets[1].url in ask.prompts[1]


def test_tweet_for_removed_handle_still_proposed_this_run(monkeypatch, interests_text: str) -> None:
    """F22: R5 works the R1 snapshot; next run picks up the edited list."""
    _stub_run_deps(monkeypatch, [make_tweet(handle="removed-handle")])
    ask = AskRecorder(answers=["skip"])
    _quiet_run(ask, interests_text)
    assert len(ask.prompts) == 1


def test_unknown_external_reply_still_proposed(monkeypatch, interests_text: str) -> None:
    """F21: R5 only knows persisted files; the linked thread is the backstop."""
    _stub_run_deps(monkeypatch, [make_tweet()])
    ask = AskRecorder(answers=["skip"])
    _quiet_run(ask, interests_text)
    assert len(ask.prompts) == 1


def test_overlapping_runs_propose_independently(monkeypatch, interests_text: str) -> None:
    """F23: no locking — each run calls ask_human on its own."""
    _stub_run_deps(monkeypatch, [make_tweet()])
    ask = AskRecorder(answers=["skip", "skip"])
    _quiet_run(ask, interests_text)
    _quiet_run(ask, interests_text)
    assert len(ask.prompts) == 2


def test_confirmations_apply_per_tweet(monkeypatch, interests_text: str) -> None:
    """F24: confirming A mid-batch has no effect on B's proposal."""
    tweets = [
        make_tweet(id="1968123456789012341", url="https://x.com/u/status/1"),
        make_tweet(id="1968123456789012342", url="https://x.com/u/status/2"),
    ]
    persisted = _stub_run_deps(monkeypatch, tweets)
    monkeypatch.setattr(
        worker_mod,
        "parse_confirmation",
        lambda answer_text, today: ("111", "2026-09-26") if "111" in answer_text else None,
    )
    ask = AskRecorder(answers=["posted, reply id 111", "skip"])
    _quiet_run(ask, interests_text)
    assert len(ask.prompts) == 2
    assert tweets[0].url in ask.prompts[0]
    assert tweets[1].url in ask.prompts[1]
    assert [p["reply_id"] for p in persisted] == ["111"]


def test_same_tweet_across_runs_proposed_again_at_r5(monkeypatch, interests_text: str) -> None:
    """F25: R5 does no cross-run coordination; R6's atomic write dedupes."""
    ask = AskRecorder(answers=["skip", "skip"])
    tweet = make_tweet()
    propose_tweet(tweet, GOOD_DRAFT, ask)
    propose_tweet(tweet, GOOD_DRAFT, ask)
    assert len(ask.prompts) == 2


def test_run_today_defaults_to_date_type(monkeypatch, interests_text: str) -> None:
    """Seam sanity: an explicit posting-day date flows through the run."""
    assert isinstance(TODAY, date)
    _stub_run_deps(monkeypatch, [])
    ask = AskRecorder()
    _quiet_run(ask, interests_text)
    assert ask.prompts == []
