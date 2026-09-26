"""Shared fake for the M2 run_command seam.

Unit under test: fleet.tweet_watch.x_fetch.fetch_tweets. The fake stands in
for the ``x`` CLI: argv tuple in, stdout out, subprocess-style errors out.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from typing import Any

import pytest

CHECK_ARGV = ("x", "watch", "check", "--format", "json")


def record(
    tweet_id: Any,
    handle: str,
    text: str = "some text",
    url: str = "https://x.com/u/status/1",
    created_at: str = "2026-09-26T10:00:00Z",
    **extra: Any,
) -> dict[str, Any]:
    """One ``x watch check`` JSON item using the Tweet field names as keys."""
    item: dict[str, Any] = {
        "id": tweet_id,
        "handle": handle,
        "text": text,
        "url": url,
        "created_at": created_at,
    }
    item.update(extra)
    return item


def payload(records: list[dict[str, Any]]) -> str:
    """Encode check items as the ``check --format json`` stdout."""
    return json.dumps(records)


@dataclass
class FakeCLI:
    """Fake ``x`` CLI behind the run_command seam (argv tuple in, stdout out)."""

    calls: list[tuple[str, ...]] = field(default_factory=list)
    check_stdout: str = "[]"
    add_failures: dict[str, str] = field(default_factory=dict)
    check_exc: BaseException | None = None

    def __call__(self, argv: tuple[str, ...]) -> str:
        self.calls.append(tuple(argv))
        if tuple(argv[:3]) == ("x", "watch", "add"):
            target = argv[3]
            assert target.startswith("user:"), f"add target must be user:<handle>: {argv!r}"
            handle = target.removeprefix("user:")
            if handle in self.add_failures:
                raise subprocess.CalledProcessError(1, argv, stderr=self.add_failures[handle])
            return ""
        if tuple(argv) == CHECK_ARGV:
            if self.check_exc is not None:
                raise self.check_exc
            return self.check_stdout
        raise AssertionError(f"unexpected argv for the x CLI: {argv!r}")

    def with_payload(self, records: list[dict[str, Any]]) -> FakeCLI:
        self.check_stdout = payload(records)
        return self


@pytest.fixture
def cli() -> FakeCLI:
    return FakeCLI()
