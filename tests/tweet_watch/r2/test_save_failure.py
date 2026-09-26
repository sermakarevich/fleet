"""R2 F12/F18: save failure and crash-before-save -> next run re-emits.

Duplicate-over-loss tradeoff: the run aborts with an error naming the state
path and state is not advanced, so the same tweets surface again on retry
rather than being silently skipped. (In the full worker the tweets were
already emitted as proposals before the save; at this unit level the
observable half is: raise + no advance + re-emit on the next good run.)
"""

from __future__ import annotations

import os

import pytest

from fleet.tweet_watch.worker import find_new_tweets

from conftest import read_state_json


def _block_save_dir(tmp_path):
    """State path whose parent cannot be created: a regular file sits where
    the directory should be, so the atomic save fails deterministically."""
    blocker = tmp_path / "watch_state.json"
    blocker.write_text("{}", encoding="utf-8")
    return blocker / "nested.json"


def test_save_failure_aborts_naming_state_path(fake, make_tweet, tmp_path):
    """F12/M1 F13: unsaveable state -> error naming the state path; the
    failed save leaves no usable state behind for a silent skip."""
    path = _block_save_dir(tmp_path)
    fake.records = [make_tweet("alice", "11")]

    with pytest.raises(Exception, match="watch_state"):
        find_new_tweets(["alice"], state_path=path, run_command=fake)


def test_failed_save_reemits_on_next_run(fake, make_tweet, write_state, tmp_path):
    """F12/F18: entries never advanced by the failed run, so the next run
    emits the same tweets again (duplicates preferred over loss)."""
    bad_path = _block_save_dir(tmp_path)
    good_path = write_state({})
    fake.records = [make_tweet("alice", "11")]

    with pytest.raises(Exception, match="watch_state"):
        find_new_tweets(["alice"], state_path=bad_path, run_command=fake)

    retry = find_new_tweets(["alice"], state_path=good_path, run_command=fake)
    assert [(t.handle, t.id) for t in retry] == [("alice", "11")]
    assert read_state_json(good_path) == {"alice": "11"}


def test_crash_before_save_reemits_on_restart(fake, make_tweet, write_state):
    """F18: kill between emit and save (simulated by a read-only state dir,
    so the save dies abruptly with state unadvanced) — restart re-emits the
    same tweets instead of skipping them forever."""
    path = write_state({"alice": "10"})
    before = path.read_bytes()
    fake.records = [make_tweet("alice", "11")]
    os.chmod(path.parent, 0o555)
    try:
        with pytest.raises(Exception, match="watch_state"):
            find_new_tweets(["alice"], state_path=path, run_command=fake)
    finally:
        os.chmod(path.parent, 0o755)
    assert path.read_bytes() == before

    retry = find_new_tweets(["alice"], state_path=path, run_command=fake)
    assert [(t.handle, t.id) for t in retry] == [("alice", "11")]
    assert read_state_json(path) == {"alice": "11"}
