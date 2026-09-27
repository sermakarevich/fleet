"""R2 id comparison: numeric on all-digit ids, id-only (never created_at/text).

Covers F8 (snowflake growth across digit lengths), F14 (stored newer than
everything returned -> no regression), F15 (gaps), and the R2 contract that
comparison uses the tweet `id` only.
"""

from __future__ import annotations

from conftest import read_state_json
from fleet.tweet_watch.worker import find_new_tweets


def test_numeric_not_lexicographic_comparison(fake, make_tweet, write_state):
    """F8: stored "999" vs candidate "1000" -> 1000 is newer (lexicographic
    order would wrongly call "9..." newer and skip the tweet forever)."""
    path = write_state({"alice": "999"})
    fake.records = [make_tweet("alice", "1000")]

    result = find_new_tweets(["alice"], state_path=path, run_command=fake)

    assert [t.id for t in result] == ["1000"]
    assert read_state_json(path) == {"alice": "1000"}


def test_equal_length_ids_compare_numerically(fake, make_tweet, write_state):
    """F8: same-length ids still compare by numeric value."""
    path = write_state({"alice": "100"})
    fake.records = [make_tweet("alice", "99"), make_tweet("alice", "101")]

    result = find_new_tweets(["alice"], state_path=path, run_command=fake)

    assert [t.id for t in result] == ["101"]
    assert read_state_json(path) == {"alice": "101"}


def test_non_numeric_ids_fall_back_to_string_compare(fake, make_tweet, write_state):
    """F8: non-numeric ids compare as strings ("abd" > "abc", "abb" is not)."""
    path = write_state({"alice": "abc"})
    fake.records = [make_tweet("alice", "abb"), make_tweet("alice", "abd")]

    result = find_new_tweets(["alice"], state_path=path, run_command=fake)

    assert [t.id for t in result] == ["abd"]
    assert read_state_json(path) == {"alice": "abd"}


def test_stored_newer_than_all_returned_never_regresses(fake, make_tweet, write_state):
    """F14: deleted/purged tweets -> emit nothing and keep the newer entry."""
    path = write_state({"alice": "500"})
    fake.records = [make_tweet("alice", "400"), make_tweet("alice", "499")]
    before = path.read_bytes()

    result = find_new_tweets(["alice"], state_path=path, run_command=fake)

    assert result == []
    assert read_state_json(path) == {"alice": "500"}
    assert path.read_bytes() == before


def test_gap_in_ids_emits_everything_above_stored(fake, make_tweet, write_state):
    """F15: no gap-filling, no waiting — anything numerically greater is new."""
    path = write_state({"alice": "100"})
    fake.records = [make_tweet("alice", "102"), make_tweet("alice", "103")]

    result = find_new_tweets(["alice"], state_path=path, run_command=fake)

    assert [t.id for t in result] == ["102", "103"]
    assert read_state_json(path) == {"alice": "103"}


def test_newness_uses_id_only_not_created_at(fake, make_tweet, write_state):
    """R2 contract: newer `created_at` with an older id is NOT new; an older
    `created_at` with a newer id IS new."""
    path = write_state({"alice": "100"})
    fake.records = [
        make_tweet("alice", "99", created_at="2026-09-26T12:00:00Z"),
        make_tweet("alice", "101", created_at="2020-01-01T00:00:00Z"),
    ]

    result = find_new_tweets(["alice"], state_path=path, run_command=fake)

    assert [t.id for t in result] == ["101"]
    assert read_state_json(path) == {"alice": "101"}
