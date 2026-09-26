"""Unit under test: fleet.tweet_watch.x_fetch.fetch_tweets (M2 external errors)."""

from __future__ import annotations

import subprocess

import pytest

from fleet.tweet_watch.x_fetch import FetchError, fetch_tweets
from tests.tweet_watch.m2.conftest import FakeCLI, record


def test_watch_add_failure_names_handle_with_stderr_tail(cli: FakeCLI) -> None:
    """F11: a rejected handle errors naming it, with the CLI's stderr tail."""
    cli.add_failures["omarsar0"] = "error: account suspended (tail)"
    cli.with_payload([record("1", "typesafeai")])
    with pytest.raises(FetchError) as excinfo:
        fetch_tweets(["omarsar0", "typesafeai"], run_command=cli)
    assert excinfo.value.handle == "omarsar0"
    assert "suspended (tail)" in str(excinfo.value)


def test_watch_check_failure_names_stage_with_stderr_tail(cli: FakeCLI) -> None:
    """F12: a failed check errors naming the stage; no partial-stdout records."""
    cli.check_exc = subprocess.CalledProcessError(
        1, ("x", "watch", "check", "--format", "json"), stderr="API 429 rate limited"
    )
    with pytest.raises(FetchError) as excinfo:
        fetch_tweets(["omarsar0"], run_command=cli)
    text = f"{excinfo.value.handle} {excinfo.value}".lower()
    assert "check" in text
    assert "429" in text


@pytest.mark.parametrize(
    "stdout", ["", "<html>proxy error</html>", "INFO booted\n[]\n"], ids=["empty", "html", "log-prefix"]
)
def test_check_non_json_stdout_is_a_stage_error(cli: FakeCLI, stdout: str) -> None:
    """F13: exit-0 garbage is a JSON parse error naming the stage, never scraped."""
    cli.check_stdout = stdout
    with pytest.raises(FetchError) as excinfo:
        fetch_tweets(["omarsar0"], run_command=cli)
    text = f"{excinfo.value.handle} {excinfo.value}".lower()
    assert "check" in text or "json" in text or "parse" in text


@pytest.mark.parametrize(
    "stdout", ['{"tweets": []}', '["1", 2]'], ids=["object", "non-object-items"]
)
def test_check_wrong_shape_is_a_stage_error(cli: FakeCLI, stdout: str) -> None:
    """F14: valid JSON with the wrong shape is a shape error; state stays put."""
    cli.check_stdout = stdout
    with pytest.raises(FetchError) as excinfo:
        fetch_tweets(["omarsar0"], run_command=cli)
    text = f"{excinfo.value.handle} {excinfo.value}".lower()
    assert "check" in text


def test_hung_check_maps_to_stage_error(cli: FakeCLI) -> None:
    """F15: a killed-after-timeout check behaves exactly like a check failure."""
    cli.check_exc = subprocess.TimeoutExpired(("x", "watch", "check"), 60.0)
    with pytest.raises(FetchError) as excinfo:
        fetch_tweets(["omarsar0"], run_command=cli)
    text = f"{excinfo.value.handle} {excinfo.value}".lower()
    assert "check" in text or "timeout" in text or "timed out" in text
