"""Unit under test: fleet.tweet_watch.x_fetch.fetch_tweets (M2 default CLI path).

Covers what the injected seam cannot: the real subprocess invocation of the
``x`` binary — argv delivery, stderr tolerance (F16), a missing binary (F4),
and killing a hung binary after the timeout (F15).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from fleet.tweet_watch.x_fetch import FetchError, fetch_tweets

_FAKE_X = """#!/bin/sh
if [ "$1" = "watch" ] && [ "$2" = "add" ]; then
  echo "$3" >> "$FAKE_X_CALLS"
  exit 0
fi
if [ "$1" = "watch" ] && [ "$2" = "check" ]; then
  echo "check" >> "$FAKE_X_CALLS"
  echo "warning: slow upstream, retrying" >&2
  cat "$FAKE_X_PAYLOAD"
  exit 0
fi
echo "unexpected args: $@" >&2
exit 2
"""


@pytest.fixture
def fake_x_bin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A fake ``x`` on PATH that logs args and serves payload JSON for check."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    exe = bindir / "x"
    exe.write_text(_FAKE_X, encoding="utf-8")
    exe.chmod(0o755)
    (tmp_path / "calls.log").write_text("", encoding="utf-8")
    monkeypatch.setenv("PATH", str(bindir))
    monkeypatch.setenv("FAKE_X_CALLS", str(tmp_path / "calls.log"))
    return bindir


def _check_payload(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, items: list) -> None:
    payload_file = tmp_path / "payload.json"
    payload_file.write_text(json.dumps(items), encoding="utf-8")
    monkeypatch.setenv("FAKE_X_PAYLOAD", str(payload_file))


def test_default_seam_runs_add_then_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_x_bin: Path
) -> None:
    """The default run_command delivers the exact argv to a real x binary."""
    _check_payload(
        tmp_path,
        monkeypatch,
        [
            {
                "id": "11",
                "handle": "omarsar0",
                "text": "hi",
                "url": "u",
                "created_at": "c",
            }
        ],
    )
    (tweet,) = fetch_tweets(["omarsar0"])
    assert tweet.id == "11"
    calls = Path(os.environ["FAKE_X_CALLS"]).read_text(encoding="utf-8").splitlines()
    assert calls == ["user:omarsar0", "check"]


def test_stderr_warnings_do_not_break_valid_stdout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_x_bin: Path
) -> None:
    """F16: only stdout is parsed; stderr warnings ride along to the run log."""
    _check_payload(
        tmp_path, monkeypatch, [{"id": "1", "handle": "a", "text": "t", "url": "u", "created_at": "c"}]
    )
    out = fetch_tweets(["a"])
    assert [t.id for t in out] == ["1"]


def test_missing_binary_aborts_naming_x(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """F4: with no x on PATH the run aborts naming x instead of half-fetching."""
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(FetchError) as excinfo:
        fetch_tweets(["omarsar0", "typesafeai"])
    assert "x" in f"{excinfo.value.handle} {excinfo.value}"


def test_hung_binary_killed_after_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F15: a wedged x is killed after command_timeout and maps to a stage error."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    exe = bindir / "x"
    exe.write_text("#!/bin/sh\nexec sleep 30\n", encoding="utf-8")
    exe.chmod(0o755)
    monkeypatch.setenv("PATH", str(bindir))
    with pytest.raises(FetchError) as excinfo:
        fetch_tweets(["omarsar0"], command_timeout=2)
    text = f"{excinfo.value.handle} {excinfo.value}".lower()
    assert "check" in text or "timeout" in text or "timed out" in text
