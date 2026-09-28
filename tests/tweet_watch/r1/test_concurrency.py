"""R1 ensure_watchlist: concurrent runs agree on one seed file (F13) or one read (F14)."""

from __future__ import annotations

import threading
from pathlib import Path

from fleet.tweet_watch.kb_files import SEED_HANDLES
from fleet.tweet_watch.worker import ensure_watchlist


def _run_concurrently(path: Path, count: int) -> tuple[list, list]:
    barrier = threading.Barrier(count)
    results: list = [None] * count
    errors: list = [None] * count

    def work(i: int) -> None:
        try:
            barrier.wait(timeout=10)
            results[i] = ensure_watchlist(path)
        except Exception as exc:  # noqa: BLE001
            errors[i] = exc

    threads = [threading.Thread(target=work, args=(i,)) for i in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert not any(t.is_alive() for t in threads)
    return results, [e for e in errors if e is not None]


def test_concurrent_missing_file_yields_same_seeds(tmp_path: Path) -> None:
    path = tmp_path / "watchlist.md"
    results, errors = _run_concurrently(path, 8)
    assert errors == []
    assert all(r == list(SEED_HANDLES) for r in results)
    assert path.read_bytes() == b"omarsar0\ntypesafeai\ncloneisjun\ngoodhartproof\nSakanaAILabs\n"


def test_concurrent_existing_file_reads_same_list(tmp_path: Path) -> None:
    content = b"@omarsar0\n# note\ntypesafeai\n"
    path = tmp_path / "watchlist.md"
    path.write_bytes(content)
    results, errors = _run_concurrently(path, 8)
    assert errors == []
    assert all(r == ["omarsar0", "typesafeai"] for r in results)
    assert path.read_bytes() == content
