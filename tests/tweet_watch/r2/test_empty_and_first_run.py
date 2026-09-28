"""R2 F1/F2: empty handle list and handles with no state entry."""

from __future__ import annotations

import json

from conftest import read_state_json
from fleet.tweet_watch.worker import find_new_tweets


def test_empty_handles_emit_nothing_and_touch_nothing(fake, write_state):
    """F1: no `x` invocation, emit [], state file byte-identical."""
    path = write_state({"alice": "100"})
    before = path.read_bytes()
    mtime_before = path.stat().st_mtime_ns

    result = find_new_tweets([], state_path=path, run_command=fake)

    assert result == []
    assert fake.calls == []
    assert path.read_bytes() == before
    assert path.stat().st_mtime_ns == mtime_before


def test_empty_handles_with_missing_state_file_creates_nothing(fake, tmp_path):
    """F1: missing state file + empty handles -> [] and the file stays missing."""
    path = tmp_path / "watch_state.json"

    result = find_new_tweets([], state_path=path, run_command=fake)

    assert result == []
    assert fake.calls == []
    assert not path.exists()


def test_first_run_for_handle_emits_everything(fake, make_tweet, write_state):
    """F2: missing state entry -> every candidate is new; entry set to max id."""
    path = write_state({"alice": "10"})
    fake.records = [
        make_tweet("bob", "5"),
        make_tweet("bob", "7"),
        make_tweet("alice", "11"),
    ]

    result = find_new_tweets(["alice", "bob"], state_path=path, run_command=fake)

    assert [(t.handle, t.id) for t in result] == [
        ("bob", "5"),
        ("bob", "7"),
        ("alice", "11"),
    ]
    assert read_state_json(path) == {"alice": "11", "bob": "7"}


def test_first_run_with_missing_state_file(fake, make_tweet, tmp_path):
    """F2: no state file at all reads as {} -> all candidates new, file created."""
    path = tmp_path / "watch_state.json"
    fake.records = [make_tweet("alice", "3")]

    result = find_new_tweets(["alice"], state_path=path, run_command=fake)

    assert [(t.handle, t.id) for t in result] == [("alice", "3")]
    assert read_state_json(path) == {"alice": "3"}
    assert json.loads(path.read_text(encoding="utf-8"))["alice"] == "3"
