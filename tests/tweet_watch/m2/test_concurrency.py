"""Unit under test: fleet.tweet_watch.x_fetch.fetch_tweets (M2 overlap behaviour)."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

from fleet.tweet_watch.x_fetch import fetch_tweets
from tests.tweet_watch.m2.conftest import CHECK_ARGV, payload, record


class ThreadSeam:
    """Seam whose check stdout depends on the calling thread's last added handle."""

    def __init__(self, gate: threading.Barrier) -> None:
        self._gate = gate
        self._local = threading.local()

    def __call__(self, argv: tuple[str, ...]) -> str:
        if tuple(argv[:3]) == ("x", "watch", "add"):
            self._local.handle = argv[3].removeprefix("user:")
            return ""
        assert tuple(argv) == CHECK_ARGV
        self._gate.wait(timeout=30)
        handle = self._local.handle
        return payload([record(f"{handle}-1", handle)])


def test_overlapping_runs_parse_their_own_stdout() -> None:
    """F21: no locking in M2; concurrent checks each parse their own stdout."""
    gate = threading.Barrier(8)
    seam = ThreadSeam(gate)
    handles = [f"user{i}" for i in range(8)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda h: fetch_tweets([h], run_command=seam), handles))
    for handle, out in zip(handles, results, strict=True):
        assert [(t.handle, t.id) for t in out] == [(handle, f"{handle}-1")]


def test_concurrent_identical_runs_agree() -> None:
    """F21: concurrent adds are idempotent; identical runs return identical records."""
    gate = threading.Barrier(4)
    seam = ThreadSeam(gate)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: fetch_tweets(["omarsar0"], run_command=seam), range(4)))
    assert results == results[:1] * 4
    assert [(t.handle, t.id) for t in results[0]] == [("omarsar0", "omarsar0-1")]
