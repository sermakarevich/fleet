"""R2 F3: per-handle fetch failure skips that handle, siblings continue."""

from __future__ import annotations

import pytest

from fleet.tweet_watch.worker import find_new_tweets

from conftest import read_state_json


def test_failed_handle_emits_nothing_and_keeps_state(fake, make_tweet, write_state):
    """F3: bob's `watch add` fails -> warning naming bob, alice unaffected."""
    path = write_state({"alice": "10", "bob": "10"})
    fake.fail_add_for = {"bob"}
    fake.records = [make_tweet("alice", "11"), make_tweet("bob", "12")]

    with pytest.warns(UserWarning, match="bob"):
        result = find_new_tweets(["alice", "bob"], state_path=path, run_command=fake)

    assert [(t.handle, t.id) for t in result] == [("alice", "11")]
    state = read_state_json(path)
    assert state["alice"] == "11"
    assert state["bob"] == "10"


def test_failed_handle_alone_emits_nothing(fake, write_state):
    """F3 with a single watched handle: warning names it, emit [], no advance."""
    path = write_state({"bob": "10"})
    fake.fail_add_for = {"bob"}

    with pytest.warns(UserWarning, match="bob"):
        result = find_new_tweets(["bob"], state_path=path, run_command=fake)

    assert result == []
    assert read_state_json(path) == {"bob": "10"}
