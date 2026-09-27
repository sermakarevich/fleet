"""M3 write_reply: repo-format writes (R6, F1, F15-F17, F20-F21)."""

from __future__ import annotations

import os
import re
from datetime import date
from pathlib import Path

import pytest

from fleet.tweet_watch.reply_files import list_recent, read_reply_text, write_reply

STATS_RE = re.compile(r"likes \d+ · retweets \d+ · replies \d+ · views \d+")


def test_write_produces_repo_format(tmp_path: Path) -> None:
    replies = tmp_path / "replies"
    body = "A harness is just a loop around tool calls."
    target = write_reply(replies, "2026-09-26", "2103871751771898112", body)
    assert target == replies / "2026-09-26-2103871751771898112.md"
    assert target.exists()
    text = target.read_text(encoding="utf-8")
    assert text.splitlines()[0].startswith("# ")
    assert "> source:" in text
    assert "2103871751771898112" in text
    assert "> reply to:" in text
    assert body in text
    assert STATS_RE.search(text) is not None


def test_written_reply_is_readable_and_listed(tmp_path: Path) -> None:
    replies = tmp_path / "replies"
    body = "The loop is the product."
    target = write_reply(replies, "2026-09-26", "123", body)
    assert "The loop is the product." in read_reply_text(target)
    assert target.name in {p.name for p in list_recent(replies, date(2026, 9, 26))}


def test_write_creates_missing_dir(tmp_path: Path) -> None:
    # F1: persistence creates the dir with mkdir -p on first confirmed write.
    replies = tmp_path / "deep" / "replies"
    target = write_reply(replies, "2026-09-26", "123", "hello")
    assert target.exists()


def test_overwrite_same_path_idempotent(tmp_path: Path) -> None:
    # F16: retried run after a crash overwrites; no -2 duplicates.
    replies = tmp_path / "replies"
    replies.mkdir()
    write_reply(replies, "2026-09-26", "123", "first")
    write_reply(replies, "2026-09-26", "123", "second")
    names = [p.name for p in replies.iterdir()]
    assert names == ["2026-09-26-123.md"]
    assert "second" in (replies / "2026-09-26-123.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("bad_date", ["2026-9-5", "not-a-date", "", "2026/09/26"])
def test_bad_date_rejected_before_touching_fs(tmp_path: Path, bad_date: str) -> None:
    # F17: error names the bad value; no file written.
    replies = tmp_path / "replies"
    replies.mkdir()
    with pytest.raises(Exception) as excinfo:
        write_reply(replies, bad_date, "123", "hello")
    assert not isinstance(excinfo.value, NotImplementedError)
    assert bad_date in str(excinfo.value) or "date" in str(excinfo.value).lower()
    assert list(replies.iterdir()) == []


def test_empty_id_rejected(tmp_path: Path) -> None:
    # F17: empty id writes nothing.
    replies = tmp_path / "replies"
    replies.mkdir()
    with pytest.raises(Exception) as excinfo:
        write_reply(replies, "2026-09-26", "", "hello")
    assert not isinstance(excinfo.value, NotImplementedError)
    assert list(replies.iterdir()) == []


def test_write_failure_reports_unpersisted(tmp_path: Path) -> None:
    # F15: error names the target path; reply reported as unpersisted.
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        pytest.skip("permission bits do not apply to root")

    replies = tmp_path / "replies"
    replies.mkdir()
    replies.chmod(0o555)
    try:
        with pytest.raises(Exception) as excinfo:
            write_reply(replies, "2026-09-26", "123", "hello")
    finally:
        replies.chmod(0o755)
    assert "2026-09-26-123.md" in str(excinfo.value)
    assert not (replies / "2026-09-26-123.md").exists()


def test_write_leaves_no_temp_files(tmp_path: Path) -> None:
    # F20/F21: atomic temp file + rename — readers never see half-written
    # bodies, and no stray temp files remain.
    replies = tmp_path / "replies"
    replies.mkdir()
    write_reply(replies, "2026-09-26", "123", "complete body here")
    names = [p.name for p in replies.iterdir()]
    assert names == ["2026-09-26-123.md"]
    text = (replies / "2026-09-26-123.md").read_text(encoding="utf-8")
    assert "complete body here" in text
