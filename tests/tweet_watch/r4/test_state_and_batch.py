"""R4 recency dedupe, wrong state / batch / concurrency (F16-F20). Unit under test: fleet.tweet_watch.worker.is_duplicate (F17 also via fleet.tweet_watch.worker.run)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

import fleet.tweet_watch.worker as worker
from fleet.tweet_watch import Tweet
from fleet.tweet_watch.reply_files import list_recent, read_reply_text
from fleet.tweet_watch.worker import is_duplicate

RUN_DATE = date(2026, 9, 26)

VERIFIER_BODY = (
    "Verifier models cut false approves. We saw 30% fewer bad merges "
    "after adding a second-pass verifier to the merge queue."
)
SAME_PARAGRAPH = (
    "Verifier models cut false approves; we saw 30% fewer bad merges "
    "after adding a second-pass verifier."
)


def test_f16_hand_edited_file_compared_as_is() -> None:
    # Drift from the posted tweet is a documented limitation: dedupe
    # compares against file content as-is, so an exact match blocks.
    edited_body = VERIFIER_BODY + " [edited after posting]"
    assert is_duplicate(edited_body, [edited_body]) is True


def test_f17_second_near_identical_draft_in_batch_flagged() -> None:
    # Intra-batch dedupe applies the same rule between drafts, not just
    # against persisted files: the second draft must not pass as-is.
    assert is_duplicate(SAME_PARAGRAPH, [SAME_PARAGRAPH]) is True


def test_f17_run_proposes_first_of_two_identical_drafts_only(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    kb = tmp_path / "kb"
    watchlist = kb / "x" / "watchlist.md"
    watchlist.parent.mkdir(parents=True)
    watchlist.write_text("omarsar0\n", encoding="utf-8")
    interests = kb / "INTERESTS.md"
    interests.write_text("# interests\ncore stuff\n", encoding="utf-8")
    replies = kb / "x" / "replies"
    monkeypatch.setattr(worker, "WATCHLIST_PATH", watchlist)
    monkeypatch.setattr(worker, "STATE_PATH", kb / "x" / "watch_state.json")
    monkeypatch.setattr(worker, "INTERESTS_PATH", interests)
    monkeypatch.setattr(worker, "REPLIES_DIR", replies)

    def _tweet(i: str) -> Tweet:
        return Tweet(
            id=i,
            handle="omarsar0",
            text="Verifier models thread with real substance.",
            url=f"https://x.com/omarsar0/status/{i}",
            created_at="2026-09-26T00:00:00Z",
        )

    monkeypatch.setattr(worker, "find_new_tweets", lambda *a, **k: [_tweet("111"), _tweet("112")])
    monkeypatch.setattr(worker, "score_tweet", lambda *a, **k: "HIGH")
    monkeypatch.setattr(worker, "compose_draft", lambda *a, **k: SAME_PARAGRAPH)
    calls: list[str] = []
    monkeypatch.setattr(
        worker, "propose_tweet", lambda *a, **k: calls.append("x") or "declined"
    )
    monkeypatch.setattr(worker, "parse_confirmation", lambda *a, **k: None)
    persisted: list[str] = []
    monkeypatch.setattr(
        worker, "persist_reply", lambda *a, **k: persisted.append("x") or replies / "y.md"
    )
    worker.run(ask=lambda prompt: "declined", today=RUN_DATE)
    assert len(calls) == 1
    assert persisted == []


def test_f18_unconfirmed_draft_from_last_run_does_not_block(tmp_path: Path) -> None:
    # Dedupe is against persisted reply files only; a declined draft was
    # never stored (R6), so re-proposing it is allowed.
    replies = tmp_path / "replies"
    replies.mkdir()
    (replies / "2026-09-25-1.md").write_text(
        "Sandboxing notes: 60s default timeout.", encoding="utf-8"
    )
    recent = [read_reply_text(p) for p in list_recent(replies, RUN_DATE)]
    assert is_duplicate(VERIFIER_BODY, recent) is False


def test_f19_f20_decision_is_pure_function_of_snapshot() -> None:
    # Concurrent runs share nothing but files (M3 atomic rename); the R4
    # decision itself must be deterministic on its inputs and mutate nothing.
    recent = [VERIFIER_BODY, "Evals matter for agent quality."]
    first = is_duplicate(SAME_PARAGRAPH, recent)
    assert is_duplicate(SAME_PARAGRAPH, recent) == first
    assert is_duplicate(SAME_PARAGRAPH, list(reversed(recent))) == first
    assert recent == [VERIFIER_BODY, "Evals matter for agent quality."]
    assert is_duplicate(SAME_PARAGRAPH, tuple(recent)) == first


def test_f20_snapshot_list_is_caller_owned() -> None:
    # A file appearing mid-dedupe either lands in the snapshot or misses it;
    # either way the decision below never sees a half-written body.
    snapshot = [VERIFIER_BODY]
    assert is_duplicate(SAME_PARAGRAPH, snapshot) is True
    assert is_duplicate(
        "Brand new observation with a concrete number: 42.", snapshot
    ) is False
