"""R4 recency dedupe, fail closed on unreadable history (F13/F14). Unit under test: fleet.tweet_watch.worker.run."""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import pytest

import fleet.tweet_watch.worker as worker
from fleet.tweet_watch import Tweet

RUN_DATE = date(2026, 9, 26)

DRAFT = (
    "New number on the verifier thread: p95 verification latency is 1.8s "
    "per task at our volume, measured over last week's merges."
)

needs_posix_perms = pytest.mark.skipif(
    os.geteuid() == 0 if hasattr(os, "geteuid") else True,
    reason="permission bits do not apply to root",
)


def _wire_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, replies: Path) -> list[str]:
    kb = tmp_path / "kb"
    watchlist = kb / "x" / "watchlist.md"
    watchlist.parent.mkdir(parents=True)
    watchlist.write_text("omarsar0\n", encoding="utf-8")
    interests = kb / "INTERESTS.md"
    interests.write_text("# interests\ncore stuff\n", encoding="utf-8")
    monkeypatch.setattr(worker, "WATCHLIST_PATH", watchlist)
    monkeypatch.setattr(worker, "STATE_PATH", kb / "x" / "watch_state.json")
    monkeypatch.setattr(worker, "INTERESTS_PATH", interests)
    monkeypatch.setattr(worker, "REPLIES_DIR", replies)
    tweet = Tweet(
        id="111",
        handle="omarsar0",
        text="Verifier models thread with real substance.",
        url="https://x.com/omarsar0/status/111",
        created_at="2026-09-26T00:00:00Z",
    )
    monkeypatch.setattr(worker, "find_new_tweets", lambda *a, **k: [tweet])
    monkeypatch.setattr(worker, "score_tweet", lambda *a, **k: "HIGH")
    monkeypatch.setattr(worker, "compose_draft", lambda *a, **k: DRAFT)
    calls: list[str] = []
    monkeypatch.setattr(worker, "propose_tweet", lambda *a, **k: calls.append("x") or "no")
    return calls


@needs_posix_perms
def test_f13_unreadable_replies_dir_aborts_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Fail closed: never fall back to an empty history (that would disable
    # the dedupe and risk proposing a near-duplicate).
    replies = tmp_path / "replies"
    replies.mkdir()
    calls = _wire_run(monkeypatch, tmp_path, replies)
    replies.chmod(0o000)
    try:
        with pytest.raises(Exception) as excinfo:
            worker.run(ask=lambda prompt: "no", today=RUN_DATE)
    finally:
        replies.chmod(0o755)
    assert str(replies) in str(excinfo.value)
    assert calls == []


@needs_posix_perms
def test_f14_single_unreadable_in_window_file_aborts_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Silently skipping one file could re-propose its wording.
    replies = tmp_path / "replies"
    replies.mkdir()
    (replies / "2026-09-25-1.md").write_text("Some other reply body.", encoding="utf-8")
    bad = replies / "2026-09-25-2.md"
    bad.write_text("Verifier models cut false approves.", encoding="utf-8")
    calls = _wire_run(monkeypatch, tmp_path, replies)
    bad.chmod(0o000)
    try:
        with pytest.raises(Exception) as excinfo:
            worker.run(ask=lambda prompt: "no", today=RUN_DATE)
    finally:
        bad.chmod(0o644)
    assert bad.name in str(excinfo.value) or str(replies) in str(excinfo.value)
    assert calls == []
