"""Unit under test: fleet.tweet_watch.x_fetch.fetch_tweets (M2 boundary values)."""

from __future__ import annotations

from fleet.tweet_watch.x_fetch import fetch_tweets
from tests.tweet_watch.m2.conftest import FakeCLI, record


def test_quiet_account_returns_empty_list(cli: FakeCLI) -> None:
    """F6: no tweets since last run is an empty list, not an error."""
    cli.with_payload([])
    assert fetch_tweets(["omarsar0"], run_command=cli) == []


def test_large_check_payload_is_fully_parsed(cli: FakeCLI) -> None:
    """F7: hundreds of records / multi-MB stdout parse with no truncation."""
    records = [record(str(i), "bighandle", text=f"body {i} " + "x" * 4000) for i in range(300)]
    cli.with_payload(records)
    out = fetch_tweets(["bighandle"], run_command=cli)
    assert len(out) == 300
    assert out[0].text.startswith("body 0 ")
    assert out[-1].text.startswith("body 299 ")
    assert out[-1].text == records[-1]["text"]


def test_special_characters_preserved_verbatim(cli: FakeCLI) -> None:
    """F8: emoji, CJK, newlines, quotes, >, # survive the parse untouched."""
    text = "emoji 🎉 CJK 日本語\nnewline \"dq\" 'sq' > angle #hash @mention"
    cli.with_payload([record("8", "omarsar0", text=text)])
    (tweet,) = fetch_tweets(["omarsar0"], run_command=cli)
    assert tweet.text == text


def test_created_at_ignored_for_ordering_but_passed_through(cli: FakeCLI) -> None:
    """F9: order/dedupe use id only; created_at crosses over as-is for display."""
    cli.with_payload(
        [
            record("2", "omarsar0", created_at="2026-09-26T10:00:00+02:00"),
            record("1", "omarsar0", created_at="2026-09-25T00:00:00Z"),
        ]
    )
    out = fetch_tweets(["omarsar0"], run_command=cli)
    assert [t.id for t in out] == ["2", "1"]
    assert [t.created_at for t in out] == ["2026-09-26T10:00:00+02:00", "2026-09-25T00:00:00Z"]


def test_duplicate_id_across_handles_kept_as_separate_records(cli: FakeCLI) -> None:
    """F10: the same tweet id under two handles is two (handle, id) records."""
    cli.with_payload([record("5", "alice"), record("5", "bob")])
    out = fetch_tweets(["alice", "bob"], run_command=cli)
    assert {(t.handle, t.id) for t in out} == {("alice", "5"), ("bob", "5")}
