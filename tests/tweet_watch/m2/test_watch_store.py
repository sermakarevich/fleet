"""Unit under test: fleet.tweet_watch.x_fetch.fetch_tweets (M2 x-side store states)."""

from __future__ import annotations

from fleet.tweet_watch.x_fetch import fetch_tweets
from tests.tweet_watch.m2.conftest import CHECK_ARGV, FakeCLI, record


def test_first_run_registers_handle_and_returns_candidates(cli: FakeCLI) -> None:
    """F17: a never-added handle is registered via add, then its tweets come back."""
    cli.with_payload([record("1", "newhandle")])
    out = fetch_tweets(["newhandle"], run_command=cli)
    assert cli.calls[0] == ("x", "watch", "add", "user:newhandle")
    assert [t.id for t in out] == ["1"]


def test_reset_daemon_history_is_returned_whole(cli: FakeCLI) -> None:
    """F18: M2 never second-guesses the daemon; R2's state bounds the blast radius."""
    cli.with_payload([record(str(i), "omarsar0") for i in range(50)])
    out = fetch_tweets(["omarsar0"], run_command=cli)
    assert [t.id for t in out] == [str(i) for i in range(50)]
    assert cli.calls.count(CHECK_ARGV) == 1


def test_stale_cursor_returns_empty_without_error(cli: FakeCLI) -> None:
    """F19: an empty check is an empty result; tweets surface on a later run."""
    cli.with_payload([])
    assert fetch_tweets(["omarsar0"], run_command=cli) == []


def test_records_for_unrequested_handles_are_dropped(cli: FakeCLI) -> None:
    """F20: stale daemon-side subscriptions never leak into another handle's run."""
    cli.with_payload(
        [
            record("1", "omarsar0"),
            record("2", "ghosthandle"),
            record("3", "OMARSAR0"),
        ]
    )
    out = fetch_tweets(["omarsar0"], run_command=cli)
    assert {(t.handle, t.id) for t in out} == {("omarsar0", "1"), ("omarsar0", "3")}
