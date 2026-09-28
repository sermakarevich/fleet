"""R1 ensure_watchlist: a missing watchlist file is seeded (F1) with exact bytes (F7)."""

from __future__ import annotations

from pathlib import Path

from fleet.tweet_watch.kb_files import SEED_HANDLES
from fleet.tweet_watch.worker import ensure_watchlist

EXPECTED_BYTES = b"omarsar0\ntypesafeai\ncloneisjun\ngoodhartproof\nSakanaAILabs\n"


def test_missing_file_created_with_five_seeds_in_order(tmp_path: Path) -> None:
    path = tmp_path / "x" / "watchlist.md"
    path.parent.mkdir(parents=True)
    assert (
        ensure_watchlist(path)
        == list(SEED_HANDLES)
        == [
            "omarsar0",
            "typesafeai",
            "cloneisjun",
            "goodhartproof",
            "SakanaAILabs",
        ]
    )
    assert path.read_bytes() == EXPECTED_BYTES


def test_seed_file_content_exactness(tmp_path: Path) -> None:
    path = tmp_path / "watchlist.md"
    ensure_watchlist(path)
    raw = path.read_bytes()
    assert raw == EXPECTED_BYTES
    assert b"\r" not in raw
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert raw.endswith(b"\n") and not raw.endswith(b"\n\n")
    assert raw.decode("utf-8").splitlines() == list(SEED_HANDLES)


def test_second_run_reads_existing_seed_file(tmp_path: Path) -> None:
    path = tmp_path / "watchlist.md"
    first = ensure_watchlist(path)
    before = path.read_bytes()
    assert ensure_watchlist(path) == first == list(SEED_HANDLES)
    assert path.read_bytes() == before
