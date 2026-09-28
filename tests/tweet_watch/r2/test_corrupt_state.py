"""R2 F4: corrupt state aborts before any fetch; never resets to {}."""

from __future__ import annotations

import pytest

from fleet.tweet_watch.worker import find_new_tweets


@pytest.mark.parametrize(
    "bad_body",
    [
        "{truncated json",
        '["not", "a", "map"]',
        '"just a string"',
        "null",
        '{"alice": null}',
        '{"alice": true}',
        '{"alice": ["1"]}',
        '{"alice": {"id": "1"}}',
    ],
    ids=[
        "invalid-json",
        "list-top-level",
        "string-top-level",
        "null-top-level",
        "null-value",
        "bool-value",
        "list-value",
        "dict-value",
    ],
)
def test_corrupt_state_aborts_before_fetch(fake, tmp_path, bad_body):
    """F4/M1 F14-F16: error names the state path (and handle key for bad
    values); nothing fetched, nothing written, never reset to {}."""
    path = tmp_path / "watch_state.json"
    path.write_text(bad_body, encoding="utf-8")
    before = path.read_bytes()

    with pytest.raises(Exception, match="watch_state"):
        find_new_tweets(["alice"], state_path=path, run_command=fake)

    assert fake.calls == []
    assert path.read_bytes() == before
