"""R9 verify-run failures (F11, F14-F17, F20-F23): bad runtime situations.

The schedule entry stays installed through run-time failures; the run
itself must fail loud, keep state safe, and never invent data.
"""

from __future__ import annotations

import json
import shutil

import pytest

from fleet.tweet_watch import worker
from fleet.tweet_watch.kb_files import SEED_HANDLES

from .conftest import (
    TODAY,
    AskLog,
    canned_fetch,
    make_tweet,
    run_or_fail_scaffold,
    write_interests,
    write_watchlist,
)


def _not_scaffold(excinfo: pytest.ExceptionInfo) -> None:
    assert not isinstance(excinfo.value, NotImplementedError)


def test_over_limit_draft_is_postable_before_proposing(kb, monkeypatch) -> None:
    write_watchlist(kb, ["typesafeai"])
    write_interests(kb)
    canned_fetch(monkeypatch, [make_tweet()])
    ask = AskLog()
    run_or_fail_scaffold(ask=ask, today=TODAY, recent_texts=[])
    assert len(ask.messages) == 1
    url = "https://x.com/typesafeai/status/300"
    draft = ask.messages[0].replace(url, "").strip()
    assert draft
    assert len(draft) <= 280


def test_x_failure_names_handle_and_leaves_state_untouched(kb, monkeypatch) -> None:
    write_watchlist(kb, ["typesafeai"])
    write_interests(kb)
    before = json.dumps({"typesafeai": "100"}).encode()
    kb.state.write_bytes(before)
    canned_fetch(
        monkeypatch,
        exc=RuntimeError("x watch check failed for handle typesafeai: exit 1"),
    )
    with pytest.raises(Exception) as excinfo:
        worker.run(ask=AskLog(), today=TODAY, recent_texts=[])
    _not_scaffold(excinfo)
    assert "typesafeai" in str(excinfo.value)
    assert kb.state.read_bytes() == before


def test_missing_interests_aborts_proposals(kb, monkeypatch) -> None:
    write_watchlist(kb, ["typesafeai"])
    assert not kb.interests.exists()
    canned_fetch(monkeypatch, [make_tweet()])
    ask = AskLog()
    # Fail closed: the run raises (see r5) and nothing is proposed.
    with pytest.raises(OSError, match="INTERESTS.md"):
        worker.run(ask=ask, today=TODAY, interests_text=None, recent_texts=[])
    assert ask.messages == []


def test_ask_human_down_records_unproposed_and_raises(kb, monkeypatch) -> None:
    write_watchlist(kb, ["typesafeai"])
    write_interests(kb)
    canned_fetch(monkeypatch, [make_tweet("300"), make_tweet("301")])
    ask = AskLog(error=RuntimeError("operator console down"))
    with pytest.raises(Exception) as excinfo:
        worker.run(ask=ask, today=TODAY, recent_texts=[])
    _not_scaffold(excinfo)
    assert len(ask.messages) == 2
    assert list(kb.replies.iterdir()) == []


def test_missing_kb_parent_routes_through_ensure(kb, monkeypatch) -> None:
    shutil.rmtree(kb.root)
    assert not kb.watchlist.exists()
    write_interests(kb)
    canned_fetch(monkeypatch, [])
    run_or_fail_scaffold(ask=AskLog(), today=TODAY, recent_texts=[])
    assert kb.watchlist.read_text(encoding="utf-8").split() == list(SEED_HANDLES)


def test_corrupt_state_aborts_naming_state_file(kb, monkeypatch) -> None:
    write_watchlist(kb, ["typesafeai"])
    write_interests(kb)
    kb.state.write_text("not json{{", encoding="utf-8")
    before = kb.state.read_bytes()
    canned_fetch(monkeypatch, [make_tweet()])
    with pytest.raises(Exception) as excinfo:
        worker.run(ask=AskLog(), today=TODAY, recent_texts=[])
    _not_scaffold(excinfo)
    assert "watch_state.json" in str(excinfo.value)
    assert kb.state.read_bytes() == before


def test_missing_watchlist_is_seeded(kb, monkeypatch) -> None:
    assert not kb.watchlist.exists()
    write_interests(kb)
    canned_fetch(monkeypatch, [])
    run_or_fail_scaffold(ask=AskLog(), today=TODAY, recent_texts=[])
    assert kb.watchlist.read_text(encoding="utf-8").split() == list(SEED_HANDLES)


def test_existing_watchlist_is_never_overwritten(kb, monkeypatch) -> None:
    write_watchlist(kb, ["somehandle"])
    write_interests(kb)
    canned_fetch(monkeypatch, [])
    run_or_fail_scaffold(ask=AskLog(), today=TODAY, recent_texts=[])
    assert kb.watchlist.read_text(encoding="utf-8").split() == ["somehandle"]


def test_confirmation_without_id_stores_nothing(kb, monkeypatch) -> None:
    write_watchlist(kb, ["typesafeai"])
    write_interests(kb)
    canned_fetch(monkeypatch, [make_tweet()])
    ask = AskLog(answers=["looks good, posted!"])
    run_or_fail_scaffold(ask=ask, today=TODAY, recent_texts=[])
    assert len(ask.messages) == 1
    assert list(kb.replies.iterdir()) == []


def test_deleted_source_is_proposed_once_with_link(kb, monkeypatch) -> None:
    write_watchlist(kb, ["typesafeai"])
    write_interests(kb)
    tweet = make_tweet()
    canned_fetch(monkeypatch, [tweet])
    ask = AskLog()
    run_or_fail_scaffold(ask=ask, today=TODAY, recent_texts=[])
    assert len(ask.messages) == 1
    assert tweet.url in ask.messages[0]
    assert tweet.text.split()[0] in ask.messages[0]
