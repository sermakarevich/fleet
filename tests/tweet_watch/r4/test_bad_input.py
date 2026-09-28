"""R4 recency dedupe, bad or missing input (F1-F3).

Unit under test: fleet.tweet_watch.worker.is_duplicate.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from fleet.tweet_watch.reply_files import list_recent, read_reply_text
from fleet.tweet_watch.worker import is_duplicate

RUN_DATE = date(2026, 9, 26)

VERIFIER_BODY = (
    "Verifier models cut false approves. We saw 30% fewer bad merges "
    "after adding a second-pass verifier to the merge queue."
)
SUBSTANTIVE_DRAFT = (
    "New number on the verifier thread: p95 verification latency is 1.8s "
    "per task at our volume, measured over last week's merges."
)


def test_f1_empty_draft_flagged_for_rewrite() -> None:
    # Empty draft has nothing new added (R5 needs a concrete observation).
    assert is_duplicate("", [VERIFIER_BODY]) is True


def test_f1_whitespace_only_draft_flagged_for_rewrite() -> None:
    assert is_duplicate("   \n\t  ", [VERIFIER_BODY]) is True


def test_f1_empty_draft_blocked_even_with_empty_history() -> None:
    # Never proposed, even when there is nothing to compare against.
    assert is_duplicate("", []) is True


def test_f2_link_only_draft_flagged_for_rewrite() -> None:
    assert is_duplicate("this 👇 https://x.com/someone/status/123", [VERIFIER_BODY]) is True


def test_f2_mention_and_emoji_only_draft_flagged_for_rewrite() -> None:
    assert is_duplicate("@typesafeai 🔥🔥", []) is True


def test_f3_empty_in_window_bodies_never_block() -> None:
    # 0-byte / boilerplate-only files contribute nothing to the comparison.
    assert is_duplicate(SUBSTANTIVE_DRAFT, ["", "   ", "\n"]) is False


def test_f3_zero_byte_reply_file_does_not_block(tmp_path: Path) -> None:
    replies = tmp_path / "replies"
    replies.mkdir()
    (replies / "2026-09-25-5.md").write_bytes(b"")
    recent = [read_reply_text(p) for p in list_recent(replies, RUN_DATE)]
    assert is_duplicate(SUBSTANTIVE_DRAFT, recent) is False
