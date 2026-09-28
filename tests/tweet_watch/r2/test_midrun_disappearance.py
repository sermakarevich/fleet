"""R2 F13: state file deleted mid-run -> save recreates from memory."""

from __future__ import annotations

from conftest import read_state_json
from fleet.tweet_watch.worker import find_new_tweets


def test_midrun_deletion_recreates_state_from_memory(fake, make_tweet, write_state):
    """F13: operator deletes the file between load and save -> the save
    recreates it via mkdir -p + atomic write with the in-memory baseline
    plus this run's advances."""
    path = write_state({"alice": "10", "gone": "5"})
    fake.records = [make_tweet("alice", "11")]
    fake.on_check = path.unlink

    result = find_new_tweets(["alice"], state_path=path, run_command=fake)

    assert [(t.handle, t.id) for t in result] == [("alice", "11")]
    assert path.exists()
    assert read_state_json(path) == {"alice": "11", "gone": "5"}
