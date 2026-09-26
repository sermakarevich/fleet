"""R2 F7/F17: large backlogs emit in full; x-side reset bounded by state."""

from __future__ import annotations

from fleet.tweet_watch.worker import find_new_tweets

from conftest import read_state_json


def test_first_run_backlog_emits_all_without_truncation(fake, make_tweet, tmp_path):
    """F7: hundreds of candidates on a first run all emit once; state=max id."""
    path = tmp_path / "watch_state.json"
    fake.records = [make_tweet("alice", str(i)) for i in range(1, 301)]

    result = find_new_tweets(["alice"], state_path=path, run_command=fake)

    assert [t.id for t in result] == [str(i) for i in range(1, 301)]
    assert read_state_json(path) == {"alice": "300"}


def test_cursor_reset_bounded_by_stored_state(fake, make_tweet, write_state):
    """F17/M2 F18: daemon returns full history -> only ids newer than stored
    emit; state jumps to the max returned id."""
    path = write_state({"alice": "500"})
    fake.records = [make_tweet("alice", str(i)) for i in range(1, 1001)]

    result = find_new_tweets(["alice"], state_path=path, run_command=fake)

    assert [t.id for t in result] == [str(i) for i in range(501, 1001)]
    assert read_state_json(path) == {"alice": "1000"}
