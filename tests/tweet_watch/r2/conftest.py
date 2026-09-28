"""Shared harness for R2 (new-tweet detection) tests.

R2 scope: ``fleet.tweet_watch.worker.find_new_tweets`` — fetch candidates via
M2, emit only ids newer than ``watch_state.json``, persist newest ids via M1.
These tests drive the real ``find_new_tweets`` with a fake ``run_command``
seam and tmp state files; the unit under test itself is never stubbed.

Seam contract pinned here for the R2/M2 implementers (mirrors
``subprocess.run(..., check=True)``):
- ``run_command(argv)`` takes an argv tuple and returns stdout as ``str``.
- CLI failure (non-zero exit, missing ``x`` binary, timeout) raises:
  ``subprocess.CalledProcessError``, ``FileNotFoundError``,
  ``subprocess.TimeoutExpired`` respectively.
- ``("x", "watch", "add", "user:<handle>")`` returns ``""`` on success.
- ``("x", "watch", "check", "--format", "json")`` returns a JSON stdout string.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest


class FakeX:
    """Fake ``x`` CLI behind the ``run_command`` seam."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.records: list[dict] = []
        self.raw_check_stdout: str | None = None
        self.fail_add_for: set[str] = set()
        self.fail_check: BaseException | None = None
        self.on_add = None
        self.on_check = None

    def __call__(self, argv: tuple[str, ...]) -> str:
        argv = tuple(argv)
        self.calls.append(argv)
        if list(argv[:3]) == ["x", "watch", "add"]:
            handle = argv[3].split("user:", 1)[1] if len(argv) > 3 else ""
            if self.on_add is not None:
                self.on_add(handle)
            if handle in self.fail_add_for:
                raise subprocess.CalledProcessError(1, argv, stderr=f"no such user: {handle}")
            return ""
        if list(argv[:3]) == ["x", "watch", "check"]:
            if self.on_check is not None:
                self.on_check()
            if self.fail_check is not None:
                raise self.fail_check
            if self.raw_check_stdout is not None:
                return self.raw_check_stdout
            return json.dumps(self.records)
        raise AssertionError(f"unexpected argv: {argv!r}")

    @property
    def check_calls(self) -> list[tuple[str, ...]]:
        return [c for c in self.calls if list(c[:3]) == ["x", "watch", "check"]]

    @property
    def add_calls(self) -> list[tuple[str, ...]]:
        return [c for c in self.calls if list(c[:3]) == ["x", "watch", "add"]]


@pytest.fixture
def fake() -> FakeX:
    return FakeX()


@pytest.fixture
def make_tweet():
    def _make(handle: str, tid: str | int, **kw) -> dict:
        rec = {
            "id": tid,
            "handle": handle,
            "text": kw.get("text", f"post {tid} by {handle}"),
            "url": kw.get("url", f"https://x.com/{handle}/status/{tid}"),
            "created_at": kw.get("created_at", "2026-09-26T10:00:00Z"),
        }
        rec.update(kw)
        return rec

    return _make


@pytest.fixture
def write_state(tmp_path: Path):
    def _write(state: dict) -> Path:
        path = tmp_path / "watch_state.json"
        path.write_text(json.dumps(state), encoding="utf-8")
        return path

    return _write


def read_state_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))
