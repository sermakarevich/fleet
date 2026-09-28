"""R2 F9/F10: duplicate ids deduped; single tweet emitted exactly once."""

from __future__ import annotations

from conftest import read_state_json
from fleet.tweet_watch.worker import find_new_tweets


def test_duplicate_id_in_one_payload_emitted_once(fake, make_tweet, write_state):
    """F9: same (handle, id) twice in one check payload -> emitted once."""
    path = write_state({})
    fake.records = [make_tweet("alice", "7"), make_tweet("alice", "7")]

    result = find_new_tweets(["alice"], state_path=path, run_command=fake)

    assert [(t.handle, t.id) for t in result] == [("alice", "7")]
    assert read_state_json(path) == {"alice": "7"}


def test_single_new_tweet_exactly_once_across_runs(fake, make_tweet, write_state):
    """F10 + R2 observable: emitted exactly once; the next run emits nothing
    and a new tweet appears exactly once across consecutive runs."""
    path = write_state({"alice": "10"})
    fake.records = [make_tweet("alice", "11")]

    first = find_new_tweets(["alice"], state_path=path, run_command=fake)
    assert [(t.handle, t.id) for t in first] == [("alice", "11")]
    assert read_state_json(path) == {"alice": "11"}

    second = find_new_tweets(["alice"], state_path=path, run_command=fake)
    assert second == []


def test_same_id_under_two_handles_tracked_independently(fake, make_tweet, write_state):
    """M2 F10 at R2 level: id 50 for both alice and bob are separate records;
    per-handle state dedupes each side independently."""
    path = write_state({"alice": "49", "bob": "50"})
    fake.records = [make_tweet("alice", "50"), make_tweet("bob", "50")]

    result = find_new_tweets(["alice", "bob"], state_path=path, run_command=fake)

    assert [(t.handle, t.id) for t in result] == [("alice", "50")]
    assert read_state_json(path) == {"alice": "50", "bob": "50"}
