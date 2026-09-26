"""R2 F11: run-wide `check` failure -> nothing emitted, state untouched."""

from __future__ import annotations

import subprocess

import pytest

from fleet.tweet_watch import FetchError
from fleet.tweet_watch.worker import find_new_tweets

from conftest import read_state_json


def test_check_nonzero_exit_emits_nothing(fake, make_tweet, write_state):
    """F11/M2 F12: check fails -> error naming the check stage, no partial
    results persisted, every entry left for the next run to retry."""
    path = write_state({"alice": "10", "bob": "20"})
    before = path.read_bytes()
    fake.records = [make_tweet("alice", "11")]
    fake.fail_check = subprocess.CalledProcessError(
        1, ("x", "watch", "check"), stderr="network down"
    )

    with pytest.raises(FetchError, match="check"):
        find_new_tweets(["alice", "bob"], state_path=path, run_command=fake)

    assert path.read_bytes() == before
    assert read_state_json(path) == {"alice": "10", "bob": "20"}


def test_check_garbage_stdout_emits_nothing(fake, write_state):
    """F11/M2 F13: exit 0 but unparseable stdout -> error, state untouched,
    never falls back to scraping the garbage."""
    path = write_state({"alice": "10"})
    before = path.read_bytes()
    fake.raw_check_stdout = "<html>502 bad gateway</html>"

    with pytest.raises(FetchError, match="check"):
        find_new_tweets(["alice"], state_path=path, run_command=fake)

    assert path.read_bytes() == before


def test_check_timeout_emits_nothing(fake, write_state):
    """F11/M2 F15: hung `x` killed by timeout behaves like a check failure."""
    path = write_state({"alice": "10"})
    before = path.read_bytes()
    fake.fail_check = subprocess.TimeoutExpired(("x", "watch", "check"), 60.0)

    with pytest.raises(FetchError, match="check"):
        find_new_tweets(["alice"], state_path=path, run_command=fake)

    assert path.read_bytes() == before
