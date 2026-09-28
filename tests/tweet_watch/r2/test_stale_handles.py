"""R2 F16: state entries for removed handles are preserved untouched."""

from __future__ import annotations

from conftest import read_state_json
from fleet.tweet_watch.worker import find_new_tweets


def test_stale_handle_entries_preserved_on_save(fake, make_tweet, write_state):
    """F16/M1 F17: entries for handles no longer in the watchlist are kept
    as-is; re-adding the handle later must not re-emit old tweets."""
    path = write_state({"alice": "10", "removed": "42"})
    fake.records = [make_tweet("alice", "11")]

    result = find_new_tweets(["alice"], state_path=path, run_command=fake)

    assert [(t.handle, t.id) for t in result] == [("alice", "11")]
    assert read_state_json(path) == {"alice": "11", "removed": "42"}


def test_readded_handle_does_not_reemit_old_tweets(fake, make_tweet, write_state):
    """F16 follow-through: after a run that preserved the stale entry,
    re-adding the handle emits only tweets newer than the preserved id."""
    path = write_state({"alice": "10", "bob": "42"})
    fake.records = [make_tweet("alice", "11")]
    find_new_tweets(["alice"], state_path=path, run_command=fake)

    fake.records = [make_tweet("bob", "40"), make_tweet("bob", "43")]
    result = find_new_tweets(["alice", "bob"], state_path=path, run_command=fake)

    assert [(t.handle, t.id) for t in result] == [("bob", "43")]
    assert read_state_json(path) == {"alice": "11", "bob": "43"}
