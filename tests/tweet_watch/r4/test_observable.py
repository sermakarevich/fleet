"""R4 recency dedupe observable. Unit under test: fleet.tweet_watch.worker.is_duplicate."""

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
NEW_ANGLE_DRAFT = (
    "Same verifier topic, new number: verification now costs us $0.004 "
    "per verified task at current volume, measured over last week's merges."
)


def _recent_texts(replies_dir: Path) -> list[str]:
    return [read_reply_text(p) for p in list_recent(replies_dir, RUN_DATE)]


def test_copy_from_last_3_days_is_rejected(tmp_path: Path) -> None:
    replies = tmp_path / "replies"
    replies.mkdir()
    (replies / "2026-09-25-101.md").write_text(VERIFIER_BODY, encoding="utf-8")
    assert is_duplicate(VERIFIER_BODY, _recent_texts(replies)) is True


def test_draft_on_new_angle_passes(tmp_path: Path) -> None:
    replies = tmp_path / "replies"
    replies.mkdir()
    (replies / "2026-09-25-101.md").write_text(VERIFIER_BODY, encoding="utf-8")
    assert is_duplicate(NEW_ANGLE_DRAFT, _recent_texts(replies)) is False


def test_reply_older_than_3_days_does_not_block(tmp_path: Path) -> None:
    replies = tmp_path / "replies"
    replies.mkdir()
    (replies / "2026-09-22-101.md").write_text(VERIFIER_BODY, encoding="utf-8")
    assert is_duplicate(VERIFIER_BODY, _recent_texts(replies)) is False
