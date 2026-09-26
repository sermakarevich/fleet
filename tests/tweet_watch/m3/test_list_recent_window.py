"""M3 list_recent: recency-window selection (normal + F8-F11)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from fleet.tweet_watch.reply_files import list_recent

RUN_DATE = date(2026, 9, 26)


def _touch(replies: Path, name: str, mtime_old_days: int | None = None) -> Path:
    p = replies / name
    p.write_text("body\n", encoding="utf-8")
    if mtime_old_days is not None:
        import os
        import time

        old = time.time() - mtime_old_days * 86400
        os.utime(p, (old, old))
    return p


def test_in_window_files_listed_old_excluded(tmp_path: Path) -> None:
    replies = tmp_path / "replies"
    replies.mkdir()
    _touch(replies, "2026-09-26-1.md")
    _touch(replies, "2026-09-25-2.md")
    _touch(replies, "2026-09-10-3.md")
    got = {p.name for p in list_recent(replies, RUN_DATE)}
    assert got == {"2026-09-26-1.md", "2026-09-25-2.md"}


def test_boundary_exactly_3_days_counts_4_days_does_not(tmp_path: Path) -> None:
    # F8: window is inclusive of the 3rd day.
    replies = tmp_path / "replies"
    replies.mkdir()
    _touch(replies, "2026-09-23-1.md")
    _touch(replies, "2026-09-22-2.md")
    got = {p.name for p in list_recent(replies, RUN_DATE)}
    assert "2026-09-23-1.md" in got
    assert "2026-09-22-2.md" not in got


def test_future_dated_file_excluded(tmp_path: Path) -> None:
    # F9: a future file must not block drafts.
    replies = tmp_path / "replies"
    replies.mkdir()
    _touch(replies, "2026-09-27-1.md")
    _touch(replies, "2026-09-26-2.md")
    got = {p.name for p in list_recent(replies, RUN_DATE)}
    assert got == {"2026-09-26-2.md"}


def test_filename_prefix_wins_over_mtime(tmp_path: Path) -> None:
    # F10: mtime is never consulted.
    replies = tmp_path / "replies"
    replies.mkdir()
    _touch(replies, "2026-09-26-new.md", mtime_old_days=60)
    _touch(replies, "2026-07-01-old.md")
    got = {p.name for p in list_recent(replies, RUN_DATE)}
    assert got == {"2026-09-26-new.md"}


def test_empty_window_returns_empty_list(tmp_path: Path) -> None:
    # F11: quiet stretch is not an error.
    replies = tmp_path / "replies"
    replies.mkdir()
    _touch(replies, "2026-07-01-1.md")
    assert list_recent(replies, RUN_DATE) == []


def test_empty_dir_returns_empty_list(tmp_path: Path) -> None:
    replies = tmp_path / "replies"
    replies.mkdir()
    assert list_recent(replies, RUN_DATE) == []


def test_custom_window_days(tmp_path: Path) -> None:
    replies = tmp_path / "replies"
    replies.mkdir()
    _touch(replies, "2026-09-20-1.md")
    assert list_recent(replies, RUN_DATE, window_days=3) == []
    assert {p.name for p in list_recent(replies, RUN_DATE, window_days=7)} == {
        "2026-09-20-1.md"
    }
