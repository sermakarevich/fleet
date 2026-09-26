"""Unit under test: fleet.tweet_watch.x_fetch.fetch_tweets (M2 bad/missing input)."""

from __future__ import annotations

import pytest

from fleet.tweet_watch.x_fetch import FetchError, fetch_tweets
from tests.tweet_watch.m2.conftest import CHECK_ARGV, FakeCLI, record


def test_empty_handle_list_invokes_nothing(cli: FakeCLI) -> None:
    """F1: no handles means neither x command runs; returns [], not an error."""
    assert fetch_tweets([], run_command=cli) == []
    assert cli.calls == []


def test_empty_handle_list_needs_no_x_binary(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """F1: with nothing to do, a missing x CLI is still not an error."""
    monkeypatch.setenv("PATH", str(tmp_path))
    assert fetch_tweets([]) == []


def test_illegal_handle_surfaces_cli_error_naming_it(cli: FakeCLI) -> None:
    """F2: add rejects the bad handle; the error names it and yields no records."""
    cli.add_failures["user!x"] = "error: invalid handle 'user!x'"
    cli.with_payload([record("1", "goodhandle")])
    with pytest.raises(FetchError) as excinfo:
        fetch_tweets(["goodhandle", "user!x"], run_command=cli)
    assert excinfo.value.handle == "user!x"
    assert "user!x" in str(excinfo.value)
    assert CHECK_ARGV not in cli.calls


def test_handle_casing_passes_through_verbatim_and_matches_case_insensitively(
    cli: FakeCLI,
) -> None:
    """F3: the add target keeps watchlist case; records match regardless of case."""
    cli.with_payload([record("7", "sakanaailabs", text="agents")])
    (tweet,) = fetch_tweets(["SakanaAILabs"], run_command=cli)
    assert cli.calls[0] == ("x", "watch", "add", "user:SakanaAILabs")
    assert tweet.id == "7"
    assert tweet.handle == "SakanaAILabs"


def test_missing_x_binary_aborts_naming_x(cli: FakeCLI) -> None:
    """F4: no x on PATH aborts with an error naming x, never partial results."""
    cli.check_exc = FileNotFoundError(2, "x")
    with pytest.raises(FetchError) as excinfo:
        fetch_tweets(["omarsar0"], run_command=cli)
    assert "x" in f"{excinfo.value.handle} {excinfo.value}"
