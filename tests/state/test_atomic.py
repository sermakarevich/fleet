"""Tests for `state.atomic.write_text_atomic` (temp file + rename)."""
from __future__ import annotations

from pathlib import Path

from fleet.state.atomic import write_text_atomic


def test_writes_file_with_content(tmp_path: Path) -> None:
    target = tmp_path / "sub" / "marker"
    write_text_atomic(target, "1")
    assert target.read_text(encoding="utf-8") == "1"


def test_overwrite_leaves_no_tmp_sibling(tmp_path: Path) -> None:
    target = tmp_path / "task.json"
    target.write_text("old", encoding="utf-8")
    write_text_atomic(target, "new")
    assert target.read_text(encoding="utf-8") == "new"
    leftovers = [p for p in tmp_path.iterdir() if p.name != target.name]
    assert leftovers == []


def test_overwrite_is_atomic_for_readers(tmp_path: Path) -> None:
    """Reader either sees old or new content, never a torn mix."""
    import threading

    target = tmp_path / "data.txt"
    target.write_text("a" * 1000, encoding="utf-8")
    seen: set[str] = set()
    stop = threading.Event()

    def reader() -> None:
        while not stop.is_set():
            try:
                seen.add(target.read_text(encoding="utf-8"))
            except OSError:
                pass

    thread = threading.Thread(target=reader)
    thread.start()
    try:
        for i in range(50):
            write_text_atomic(target, str(i % 10) * 1000)
    finally:
        stop.set()
        thread.join()
    for content in seen:
        assert len(set(content)) == 1, "torn write observed"
