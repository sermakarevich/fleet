"""Unit under test: fleet.tweet_watch.x_fetch.fetch_tweets (M2 happy-path contract)."""

from __future__ import annotations

import inspect

from fleet.tweet_watch.x_fetch import FetchError, Tweet, fetch_tweets
from tests.tweet_watch.m2.conftest import CHECK_ARGV, FakeCLI, record


def test_add_runs_once_per_handle_then_single_check(cli: FakeCLI) -> None:
    """Adds are idempotent per-handle setup; the check is one global call, last."""
    cli.with_payload([record("1", "omarsar0"), record("2", "typesafeai")])
    out = fetch_tweets(["omarsar0", "typesafeai"], run_command=cli)
    assert [t.id for t in out] == ["1", "2"]
    assert cli.calls == [
        ("x", "watch", "add", "user:omarsar0"),
        ("x", "watch", "add", "user:typesafeai"),
        CHECK_ARGV,
    ]


def test_check_output_maps_to_tweet_records(cli: FakeCLI) -> None:
    """Stdout JSON parses into Tweet records with every field preserved."""
    cli.with_payload(
        [
            {
                "id": "42",
                "handle": "omarsar0",
                "text": "hello",
                "url": "https://x.com/omarsar0/status/42",
                "created_at": "2026-09-26T10:00:00Z",
            }
        ]
    )
    (tweet,) = fetch_tweets(["omarsar0"], run_command=cli)
    assert tweet == Tweet(
        id="42",
        handle="omarsar0",
        text="hello",
        url="https://x.com/omarsar0/status/42",
        created_at="2026-09-26T10:00:00Z",
    )


def test_records_attribute_to_their_handle(cli: FakeCLI) -> None:
    """Each record lands on the handle it was reported under."""
    cli.with_payload([record("1", "omarsar0"), record("9", "typesafeai")])
    out = fetch_tweets(["omarsar0", "typesafeai"], run_command=cli)
    assert {(t.handle, t.id) for t in out} == {("omarsar0", "1"), ("typesafeai", "9")}


def test_fetch_error_carries_handle_and_message() -> None:
    """FetchError names the failing handle (or stage) and keeps the message."""
    err = FetchError("omarsar0", "boom tail")
    assert err.handle == "omarsar0"
    assert str(err) == "boom tail"
    assert isinstance(err, Exception)


def test_seam_defaults() -> None:
    """run_command defaults to the real subprocess path; timeout defaults to 60s."""
    sig = inspect.signature(fetch_tweets)
    assert sig.parameters["run_command"].default is None
    assert sig.parameters["command_timeout"].default == 60.0
