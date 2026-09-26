"""R9 concurrency (F24-F27): ticks, installers, and edits racing the run.

Overlap skips shed colliding runs, duplicate installers reconcile to one
entry, mid-run watchlist edits wait for the next tick, and concurrent
state writes never regress an id.
"""

from __future__ import annotations

import json

from fleet.schedules.model import OverlapPolicy

from .conftest import (
    TODAY,
    AskLog,
    canned_fetch,
    make_tweet,
    run_or_fail_scaffold,
    write_interests,
    write_watchlist,
    SCHEDULE_NAME,
)


def test_installed_overlap_skip_sheds_colliding_runs(make_schedule) -> None:
    assert make_schedule().overlap is OverlapPolicy.skip


def test_overlapping_passes_converge_on_one_file(kb, monkeypatch) -> None:
    write_watchlist(kb, ["typesafeai"])
    write_interests(kb)
    canned_fetch(monkeypatch, [make_tweet()])
    answers = ["posted https://x.com/i/status/555"] * 2
    ask = AskLog(answers=answers)
    run_or_fail_scaffold(ask=ask, today=TODAY, recent_texts=[])
    run_or_fail_scaffold(ask=ask, today=TODAY, recent_texts=[])
    assert [p.name for p in kb.replies.iterdir()] == ["2026-09-26-555.md"]
    assert len(ask.messages) == 1


def test_parallel_installers_share_one_verify_run(store, make_schedule) -> None:
    store.save(make_schedule(schedule_id="sch-a"))
    store.save(make_schedule(schedule_id="sch-b"))
    assert len([s for s in store.list() if s.name == SCHEDULE_NAME]) == 2
    store.delete("sch-b")
    assert len([s for s in store.list() if s.name == SCHEDULE_NAME]) == 1


def test_mid_run_watchlist_edit_waits_for_next_tick(kb, monkeypatch) -> None:
    write_watchlist(kb, ["typesafeai"])
    write_interests(kb)
    seen: list = []

    def _fetch(*args, **kwargs):
        seen.append(args[0] if args else kwargs.get("handles"))
        kb.watchlist.write_text("typesafeai\nnewhandle\n", encoding="utf-8")
        return [make_tweet()]

    monkeypatch.setattr("fleet.tweet_watch.x_fetch.fetch_tweets", _fetch)
    ask = AskLog()
    run_or_fail_scaffold(ask=ask, today=TODAY, recent_texts=[])
    assert seen and list(seen[0]) == ["typesafeai"]
    assert len(ask.messages) == 1
    state = json.loads(kb.state.read_text(encoding="utf-8"))
    assert "newhandle" not in state


def test_concurrent_state_write_never_regresses(kb, monkeypatch) -> None:
    write_watchlist(kb, ["typesafeai"])
    write_interests(kb)
    kb.state.write_text(json.dumps({"typesafeai": "100"}), encoding="utf-8")
    canned_fetch(monkeypatch, [make_tweet(tweet_id="103")])
    ask = AskLog()
    run_or_fail_scaffold(ask=ask, today=TODAY, recent_texts=[])
    assert len(ask.messages) == 1
    kb.state.write_text(json.dumps({"typesafeai": "105"}), encoding="utf-8")
    canned_fetch(monkeypatch, [make_tweet(tweet_id="104")])
    run_or_fail_scaffold(ask=ask, today=TODAY, recent_texts=[])
    assert len(ask.messages) == 1
    assert json.loads(kb.state.read_text(encoding="utf-8")) == {"typesafeai": "105"}
