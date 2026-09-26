"""R2 F19/F20: overlapping runs never roll back state, never skip tweets.

No locking in R2; each run loads once and saves atomically. Before saving,
the run re-reads the file and merges per-handle maxima, so a slower run
never clobbers a faster run's advance (re-emit preferred over silent skip).
"""

from __future__ import annotations

import json

from fleet.tweet_watch.worker import find_new_tweets

from conftest import read_state_json


def test_slower_run_merges_instead_of_rolling_back(fake, make_tweet, write_state):
    """F20: run B saves alice->102 while run A (which saw only ->101) is
    still in flight; A's save must keep the max, and the next run emits
    nothing (no re-emit, and crucially no skip of 102)."""
    path = write_state({"alice": "100"})
    fake.records = [make_tweet("alice", "101")]

    def concurrent_faster_run():
        path.write_text(json.dumps({"alice": "102"}), encoding="utf-8")

    fake.on_check = concurrent_faster_run

    result = find_new_tweets(["alice"], state_path=path, run_command=fake)

    assert [(t.handle, t.id) for t in result] == [("alice", "101")]
    assert read_state_json(path) == {"alice": "102"}

    fake.on_check = None
    fake.records = [make_tweet("alice", "101"), make_tweet("alice", "102")]
    assert find_new_tweets(["alice"], state_path=path, run_command=fake) == []


def test_concurrent_new_handle_entry_survives_merge(fake, make_tweet, write_state):
    """F20: run A covers [alice] while run B adds bob->7 mid-flight; A's save
    must not clobber bob's entry."""
    path = write_state({"alice": "100"})
    fake.records = [make_tweet("alice", "101")]

    def concurrent_add():
        path.write_text(
            json.dumps({"alice": "100", "bob": "7"}), encoding="utf-8"
        )

    fake.on_check = concurrent_add

    find_new_tweets(["alice"], state_path=path, run_command=fake)

    assert read_state_json(path) == {"alice": "101", "bob": "7"}


def test_save_leaves_no_temp_files_behind(fake, make_tweet, write_state):
    """F19/M1 F18: atomic temp-file + rename save; readers never see a
    half-written file and no stray temp files remain in the state dir."""
    path = write_state({"alice": "100"})
    fake.records = [make_tweet("alice", "101")]

    find_new_tweets(["alice"], state_path=path, run_command=fake)

    leftovers = [
        p for p in path.parent.iterdir() if p.name != path.name
    ]
    assert leftovers == []
    assert read_state_json(path) == {"alice": "101"}
