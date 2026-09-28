"""R1 ensure_watchlist: an existing file is never overwritten or reseeded (F2, F5, F6)."""

from __future__ import annotations

from pathlib import Path

from fleet.tweet_watch.worker import ensure_watchlist


def test_empty_file_returns_empty_and_is_not_seeded(tmp_path: Path) -> None:
    path = tmp_path / "watchlist.md"
    path.write_bytes(b"")
    assert ensure_watchlist(path) == []
    assert path.read_bytes() == b""


def test_comment_and_whitespace_only_file_returns_empty(tmp_path: Path) -> None:
    content = b"# my list\n   \n\t\n# another comment\n"
    path = tmp_path / "watchlist.md"
    path.write_bytes(content)
    assert ensure_watchlist(path) == []
    assert path.read_bytes() == content


def test_custom_handles_are_kept_verbatim(tmp_path: Path) -> None:
    content = b"somehandle\nOtherHandle\n"
    path = tmp_path / "watchlist.md"
    path.write_bytes(content)
    assert ensure_watchlist(path) == ["somehandle", "OtherHandle"]
    assert path.read_bytes() == content


def test_all_invalid_lines_are_not_repaired(tmp_path: Path) -> None:
    content = b"not a handle\nuser!x\n"
    path = tmp_path / "watchlist.md"
    path.write_bytes(content)
    result = ensure_watchlist(path)
    assert isinstance(result, list) and len(result) == 2
    assert result != ["omarsar0", "typesafeai", "cloneisjun", "goodhartproof", "SakanaAILabs"]
    assert path.read_bytes() == content
