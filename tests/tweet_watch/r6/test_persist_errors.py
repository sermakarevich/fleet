"""R6 external errors and independence.

Covers F4/F5 at the persist gate (bad id/date name the value, no file),
F13 (ask_human failure -> unconfirmed, nothing stored), F14 (missing dir
created), F15 (write failure names the path, reply unpersisted),
F19 (watchlist/state untouched), F21/F22 (atomic write, no half-written body).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from fleet.tweet_watch.worker import parse_confirmation, persist_reply


@pytest.mark.parametrize("bad_id", ["abc", "12x34", ""])
def test_bad_reply_id_names_value_and_writes_nothing(
    replies_dir: Path, source_url: str, source_body: str, posted_text: str, bad_id: str
) -> None:
    with pytest.raises(Exception) as excinfo:
        persist_reply(source_url, source_body, posted_text, bad_id, "2026-09-26", replies_dir)
    assert not isinstance(excinfo.value, NotImplementedError)
    if bad_id:
        assert bad_id in str(excinfo.value) or "id" in str(excinfo.value).lower()
    assert list(replies_dir.iterdir()) == []


@pytest.mark.parametrize("bad_date", ["26/09/2026", "yesterday", "2026-9-5", ""])
def test_bad_post_date_names_value_and_writes_nothing(
    replies_dir: Path,
    source_url: str,
    source_body: str,
    posted_text: str,
    reply_id: str,
    bad_date: str,
) -> None:
    with pytest.raises(Exception) as excinfo:
        persist_reply(source_url, source_body, posted_text, reply_id, bad_date, replies_dir)
    assert not isinstance(excinfo.value, NotImplementedError)
    if bad_date:
        assert bad_date in str(excinfo.value) or "date" in str(excinfo.value).lower()
    assert list(replies_dir.iterdir()) == []


def test_f13_tool_failure_means_no_answer_means_unconfirmed(replies_dir: Path, today) -> None:
    assert parse_confirmation("", today) is None
    assert list(replies_dir.iterdir()) == []


def test_f14_missing_replies_dir_created_on_first_write(
    tmp_path: Path, source_url: str, source_body: str, posted_text: str, reply_id: str
) -> None:
    replies = tmp_path / "media" / "x" / "replies"
    assert not replies.exists()
    target = persist_reply(source_url, source_body, posted_text, reply_id, "2026-09-26", replies)
    assert target.exists()


def test_f15_write_failure_names_path_and_reports_unpersisted(
    tmp_path: Path, source_url: str, source_body: str, posted_text: str
) -> None:
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        pytest.skip("permission bits do not apply to root")
    replies = tmp_path / "replies"
    replies.mkdir()
    replies.chmod(0o555)
    try:
        with pytest.raises(Exception) as excinfo:
            persist_reply(source_url, source_body, posted_text, "123", "2026-09-26", replies)
    finally:
        replies.chmod(0o755)
    assert not isinstance(excinfo.value, NotImplementedError)
    assert "2026-09-26-123.md" in str(excinfo.value)
    assert not (replies / "2026-09-26-123.md").exists()


def test_f19_persist_touches_neither_watchlist_nor_state(
    tmp_path: Path, source_url: str, source_body: str, posted_text: str, reply_id: str
) -> None:
    watchlist = tmp_path / "watchlist.md"
    watchlist.write_text("omarsar0\n", encoding="utf-8")
    state = tmp_path / "watch_state.json"
    state.write_text('{"omarsar0": "1"}', encoding="utf-8")
    before_watch, before_state = watchlist.read_bytes(), state.read_bytes()
    persist_reply(
        source_url, source_body, posted_text, reply_id, "2026-09-26", tmp_path / "replies"
    )
    assert watchlist.read_bytes() == before_watch
    assert state.read_bytes() == before_state


def test_f21_f22_write_is_atomic_and_complete(
    replies_dir: Path, source_url: str, source_body: str, posted_text: str, reply_id: str
) -> None:
    target = persist_reply(
        source_url, source_body, posted_text, reply_id, "2026-09-26", replies_dir
    )
    names = [p.name for p in replies_dir.iterdir()]
    assert names == [target.name]
    assert posted_text in target.read_text(encoding="utf-8")
