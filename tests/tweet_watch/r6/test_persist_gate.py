"""R6 confirm-to-file gate: unconfirmed drafts store nothing.

Covers F6 (empty posted text), F7 (id alone with no draft/source link),
F8 (zero confirmations -> zero files), F16 (no trace: no temp or draft files).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fleet.tweet_watch.worker import parse_confirmation, persist_reply

from .conftest import TODAY, dir_snapshot


def test_f8_all_declined_run_leaves_dir_identical(replies_dir: Path, today) -> None:
    before = dir_snapshot(replies_dir)
    for answer in ["skip", "", "not this one", "posted"]:
        assert parse_confirmation(answer, today) is None
    assert dir_snapshot(replies_dir) == before == set()


def test_f8_zero_high_tweets_means_zero_proposals_zero_files(replies_dir: Path) -> None:
    assert dir_snapshot(replies_dir) == set()
    assert list(replies_dir.iterdir()) == []


def test_f6_empty_posted_text_writes_nothing(
    replies_dir: Path, source_url: str, source_body: str
) -> None:
    with pytest.raises(Exception) as excinfo:
        persist_reply(source_url, source_body, "   ", "123", "2026-09-26", replies_dir)
    assert not isinstance(excinfo.value, NotImplementedError)
    assert list(replies_dir.iterdir()) == []


def test_f7_id_alone_with_no_source_link_writes_nothing(replies_dir: Path) -> None:
    with pytest.raises(Exception) as excinfo:
        persist_reply("", "", "some text", "123", "2026-09-26", replies_dir)
    assert not isinstance(excinfo.value, NotImplementedError)
    assert list(replies_dir.iterdir()) == []


def test_f16_unconfirmed_run_leaves_no_temp_or_draft_files(
    replies_dir: Path, source_url: str, source_body: str, posted_text: str, reply_id: str
) -> None:
    assert parse_confirmation("skip", TODAY) is None
    before = dir_snapshot(replies_dir)
    assert before == set()
    names = [p.name for p in replies_dir.iterdir()]
    assert not any(n.startswith(("draft-", "tmp", ".")) for n in names)
    assert not any(n.endswith((".tmp", ".part")) for n in names)
