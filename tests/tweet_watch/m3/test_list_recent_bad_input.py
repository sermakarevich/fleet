"""M3 list_recent: bad or missing input (F1-F4)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from fleet.tweet_watch.reply_files import list_recent

RUN_DATE = date(2026, 9, 26)


def test_missing_replies_dir_returns_empty_list(tmp_path: Path) -> None:
    # F1: missing dir is not an error; dedupe passes everything.
    assert list_recent(tmp_path / "nope", RUN_DATE) == []


def test_non_md_files_ignored(tmp_path: Path) -> None:
    # F2: .DS_Store / *.tmp leftovers never abort the run.
    replies = tmp_path / "replies"
    replies.mkdir()
    (replies / ".DS_Store").write_bytes(b"junk")
    (replies / "2026-09-26-1.tmp").write_text("junk", encoding="utf-8")
    (replies / "draft.txt").write_text("junk", encoding="utf-8")
    (replies / "2026-09-26-1.md").write_text("body", encoding="utf-8")
    got = {p.name for p in list_recent(replies, RUN_DATE)}
    assert got == {"2026-09-26-1.md"}


def test_unparseable_filenames_excluded_run_continues(tmp_path: Path) -> None:
    # F3: notes.md, non-padded dates; never aborts the run.
    replies = tmp_path / "replies"
    replies.mkdir()
    (replies / "notes.md").write_text("body", encoding="utf-8")
    (replies / "2026-9-5-123.md").write_text("body", encoding="utf-8")
    (replies / "2026-09-26-1.md").write_text("body", encoding="utf-8")
    got = {p.name for p in list_recent(replies, RUN_DATE)}
    assert got == {"2026-09-26-1.md"}


def test_corrupt_date_prefix_excluded(tmp_path: Path) -> None:
    # F4: a file that cannot be dated must not block, nor silently count.
    replies = tmp_path / "replies"
    replies.mkdir()
    (replies / "9999-99-99-123.md").write_text("body", encoding="utf-8")
    (replies / "abcd-123.md").write_text("body", encoding="utf-8")
    (replies / "2026-09-26-1.md").write_text("body", encoding="utf-8")
    got = {p.name for p in list_recent(replies, RUN_DATE)}
    assert got == {"2026-09-26-1.md"}
