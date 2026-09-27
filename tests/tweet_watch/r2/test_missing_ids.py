"""R2 F5: candidate record missing `id` is skipped, never persisted."""

from __future__ import annotations

from conftest import read_state_json
from fleet.tweet_watch.worker import find_new_tweets


def test_record_missing_id_skipped(fake, make_tweet, write_state):
    """F5/M2 F5: id-less record never emits and never becomes the newest id;
    valid siblings still emit and the entry advances to the max valid id."""
    path = write_state({})
    good = make_tweet("alice", "9")
    bad = dict(make_tweet("alice", "10"))
    del bad["id"]
    fake.records = [bad, good]

    result = find_new_tweets(["alice"], state_path=path, run_command=fake)

    assert [(t.handle, t.id) for t in result] == [("alice", "9")]
    assert read_state_json(path) == {"alice": "9"}


def test_sole_idless_candidate_leaves_state_unchanged(fake, make_tweet, write_state):
    """F5: when the only candidate lacks an id, the stored entry is untouched."""
    path = write_state({"alice": "9"})
    bad = dict(make_tweet("alice", "10"))
    bad["id"] = None
    fake.records = [bad]

    result = find_new_tweets(["alice"], state_path=path, run_command=fake)

    assert result == []
    assert read_state_json(path) == {"alice": "9"}
