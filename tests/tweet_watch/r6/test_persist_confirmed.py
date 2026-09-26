"""R6 observable: a confirmed reply stores exactly one file in repo format.

Also covers F9 (N confirmations -> N files), F17 (posted text wins),
F18 (deleted source still stored), F20 (same source, new id -> new file).
"""

from __future__ import annotations

import re
from pathlib import Path

from fleet.tweet_watch.worker import persist_reply

STATS_RE = re.compile(r"likes \d+ · retweets \d+ · replies \d+ · views \d+")


def check_repo_format(text: str, source_url: str, posted_text: str) -> None:
    assert text.splitlines()[0].startswith("# ")
    assert "> source:" in text
    assert source_url in text
    assert "> reply to:" in text
    assert posted_text in text
    assert STATS_RE.search(text) is not None


def test_confirmed_reply_writes_exactly_one_file(
    replies_dir: Path, source_url: str, source_body: str, posted_text: str, reply_id: str
) -> None:
    target = persist_reply(
        source_url, source_body, posted_text, reply_id, "2026-09-26", replies_dir
    )
    assert target == replies_dir / "2026-09-26-2103871751771898112.md"
    assert [p.name for p in replies_dir.iterdir()] == ["2026-09-26-2103871751771898112.md"]
    check_repo_format(target.read_text(encoding="utf-8"), source_url, posted_text)


def test_f9_three_confirmations_write_three_files(
    replies_dir: Path, source_url: str, source_body: str
) -> None:
    ids = ["111", "222", "333"]
    for i, rid in enumerate(ids):
        persist_reply(
            source_url, f"{source_body} {i}", f"posted text {i}", rid, "2026-09-26", replies_dir
        )
    names = sorted(p.name for p in replies_dir.iterdir())
    assert names == [f"2026-09-26-{rid}.md" for rid in ids]


def test_f17_stores_operator_posted_text_not_stale_draft(
    replies_dir: Path, source_url: str, source_body: str
) -> None:
    stale_draft = "stale draft wording that was edited before posting"
    posted = "posted with edits: verifier models gate releases, halving bad deploys"
    target = persist_reply(source_url, stale_draft, posted, "444", "2026-09-26", replies_dir)
    text = target.read_text(encoding="utf-8")
    assert posted in text
    assert stale_draft not in text


def test_f18_deleted_source_link_still_stored(
    replies_dir: Path, source_body: str, posted_text: str
) -> None:
    dead_url = "https://x.com/someone/status/9999999999999999999"
    target = persist_reply(dead_url, source_body, posted_text, "555", "2026-09-26", replies_dir)
    assert target.exists()
    text = target.read_text(encoding="utf-8")
    assert dead_url in text
    assert posted_text in text


def test_f20_same_source_new_reply_id_writes_second_file(
    replies_dir: Path, source_url: str, source_body: str, posted_text: str
) -> None:
    persist_reply(source_url, source_body, posted_text, "666", "2026-09-26", replies_dir)
    persist_reply(source_url, source_body, "second reply, different angle", "777", "2026-09-26", replies_dir)
    names = sorted(p.name for p in replies_dir.iterdir())
    assert names == ["2026-09-26-666.md", "2026-09-26-777.md"]
