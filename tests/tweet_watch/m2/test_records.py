"""Unit under test: fleet.tweet_watch.x_fetch.fetch_tweets (M2 record shaping)."""

from __future__ import annotations

from fleet.tweet_watch.x_fetch import fetch_tweets
from tests.tweet_watch.m2.conftest import FakeCLI, record


def test_record_missing_id_is_skipped_never_synthesized(cli: FakeCLI) -> None:
    """F5: null/absent ids are dropped; valid siblings are kept; no fake ids."""
    cli.with_payload(
        [
            record(None, "omarsar0", text="null id"),
            {"handle": "omarsar0", "text": "absent id"},
            record("1", "omarsar0", text="good"),
        ]
    )
    out = fetch_tweets(["omarsar0"], run_command=cli)
    assert [t.id for t in out] == ["1"]
    assert all(t.id for t in out)


def test_record_missing_optional_fields_get_empty_defaults(cli: FakeCLI) -> None:
    """F5: a record missing only url/created_at/text is kept with '' defaults."""
    cli.with_payload([{"id": "2", "handle": "omarsar0"}])
    (tweet,) = fetch_tweets(["omarsar0"], run_command=cli)
    assert (tweet.id, tweet.handle) == ("2", "omarsar0")
    assert (tweet.text, tweet.url, tweet.created_at) == ("", "", "")


def test_record_extra_keys_are_ignored(cli: FakeCLI) -> None:
    """Unknown JSON keys never leak into records or break the parse."""
    cli.with_payload([record("3", "omarsar0", likes=10, author={"name": "x"})])
    (tweet,) = fetch_tweets(["omarsar0"], run_command=cli)
    assert tweet.id == "3"


def test_numeric_id_is_coerced_to_string(cli: FakeCLI) -> None:
    """Tweet ids stay strings (R2 persists string ids) even if JSON has numbers."""
    cli.with_payload([record(123, "omarsar0")])
    (tweet,) = fetch_tweets(["omarsar0"], run_command=cli)
    assert tweet.id == "123"


def test_record_missing_handle_is_dropped(cli: FakeCLI) -> None:
    """An item that cannot be attributed to a requested handle is dropped."""
    cli.with_payload([{"id": "4", "text": "no handle"}, record("5", "omarsar0")])
    out = fetch_tweets(["omarsar0"], run_command=cli)
    assert [t.id for t in out] == ["5"]
