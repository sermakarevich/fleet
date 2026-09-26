"""R4 recency dedupe, window wiring (F8/F9/F12/F15). Units under test: fleet.tweet_watch.worker.is_duplicate with fleet.tweet_watch.reply_files."""

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


def test_f8_reply_from_exactly_3_days_ago_blocks(tmp_path: Path) -> None:
    replies = tmp_path / "replies"
    replies.mkdir()
    (replies / "2026-09-23-77.md").write_text(VERIFIER_BODY, encoding="utf-8")
    assert is_duplicate(VERIFIER_BODY, _recent_texts(replies)) is True


def test_f8_reply_from_4_days_ago_does_not_block(tmp_path: Path) -> None:
    replies = tmp_path / "replies"
    replies.mkdir()
    (replies / "2026-09-22-77.md").write_text(VERIFIER_BODY, encoding="utf-8")
    assert is_duplicate(VERIFIER_BODY, _recent_texts(replies)) is False


def test_f9_match_against_any_in_window_reply_blocks(tmp_path: Path) -> None:
    replies = tmp_path / "replies"
    replies.mkdir()
    bodies = [
        "Sandboxing notes: 60s default timeout on every tool call.",
        "Voice-agent latency: p95 1.8s per turn at our volume.",
        "Cost engineering: batch evals overnight to halve the bill.",
        VERIFIER_BODY,
        "Coding-agent review: second pair of eyes on every diff.",
    ]
    for i, body in enumerate(bodies):
        (replies / f"2026-09-25-{i}.md").write_text(body, encoding="utf-8")
    assert is_duplicate(VERIFIER_BODY, _recent_texts(replies)) is True


def test_f9_new_angle_passes_against_many_in_window_replies(tmp_path: Path) -> None:
    replies = tmp_path / "replies"
    replies.mkdir()
    (replies / "2026-09-25-0.md").write_text(VERIFIER_BODY, encoding="utf-8")
    (replies / "2026-09-24-1.md").write_text("Evals matter.", encoding="utf-8")
    assert is_duplicate(NEW_ANGLE_DRAFT, _recent_texts(replies)) is False


def test_f12_empty_window_passes_everything(tmp_path: Path) -> None:
    replies = tmp_path / "replies"
    replies.mkdir()
    assert is_duplicate(VERIFIER_BODY, _recent_texts(replies)) is False


def test_f12_missing_replies_dir_passes_everything(tmp_path: Path) -> None:
    assert list_recent(tmp_path / "nope", RUN_DATE) == []
    assert is_duplicate(VERIFIER_BODY, []) is False


def test_f15_future_dated_reply_does_not_block(tmp_path: Path) -> None:
    replies = tmp_path / "replies"
    replies.mkdir()
    (replies / "2026-09-27-99.md").write_text(VERIFIER_BODY, encoding="utf-8")
    assert is_duplicate(VERIFIER_BODY, _recent_texts(replies)) is False
