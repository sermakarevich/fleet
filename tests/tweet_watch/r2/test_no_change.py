"""R2 F6: no new tweets -> emit nothing, state file byte-identical.

This is the second-run-no-change observable from REQUIREMENTS R2.
"""

from __future__ import annotations

from fleet.tweet_watch.worker import find_new_tweets


def test_all_older_or_equal_emits_nothing_without_rewrite(
    fake, make_tweet, write_state
):
    """F6: candidate ids <= stored entry -> [] and no rewrite, no mtime touch."""
    path = write_state({"alice": "10"})
    fake.records = [make_tweet("alice", "8"), make_tweet("alice", "10")]
    before = path.read_bytes()
    mtime_before = path.stat().st_mtime_ns

    result = find_new_tweets(["alice"], state_path=path, run_command=fake)

    assert result == []
    assert path.read_bytes() == before
    assert path.stat().st_mtime_ns == mtime_before


def test_empty_check_payload_leaves_state_alone(fake, write_state):
    """F6/M2 F6: no candidates at all -> [] and the state file is untouched."""
    path = write_state({"alice": "10"})
    fake.records = []
    before = path.read_bytes()
    mtime_before = path.stat().st_mtime_ns

    result = find_new_tweets(["alice"], state_path=path, run_command=fake)

    assert result == []
    assert path.read_bytes() == before
    assert path.stat().st_mtime_ns == mtime_before
