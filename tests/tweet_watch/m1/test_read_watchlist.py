"""Unit under test: fleet.tweet_watch.kb_files.read_watchlist (M1 watchlist parsing)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from fleet.tweet_watch.kb_files import SEED_HANDLES, read_watchlist


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_seed_handles_are_the_five_spec_handles_in_order() -> None:
    """F1: the seed list R1 creates on a missing watchlist is exactly these 5."""
    assert list(SEED_HANDLES) == [
        "omarsar0",
        "typesafeai",
        "cloneisjun",
        "goodhartproof",
        "SakanaAILabs",
    ]


def test_missing_watchlist_raises_naming_the_path(tmp_path: Path) -> None:
    """F1: a missing file is an error at M1 level (creation is R1's job)."""
    missing = tmp_path / "watchlist.md"
    with pytest.raises(OSError) as excinfo:
        read_watchlist(missing)
    assert str(missing) in str(excinfo.value)


def test_basic_handles_in_file_order(tmp_path: Path) -> None:
    """One handle per line returns the ordered list."""
    path = _write(tmp_path / "watchlist.md", "omarsar0\ntypesafeai\nSakanaAILabs\n")
    assert read_watchlist(path) == ["omarsar0", "typesafeai", "SakanaAILabs"]


def test_empty_file_returns_empty_list(tmp_path: Path) -> None:
    """F2: an empty watchlist is not an error; the run fetches nothing."""
    assert read_watchlist(_write(tmp_path / "watchlist.md", "")) == []


def test_blank_lines_and_full_line_comments_ignored(tmp_path: Path) -> None:
    """F2: blank lines and `#` comment lines are skipped."""
    path = _write(
        tmp_path / "watchlist.md",
        "\n# paused for now\nomarsar0\n\n#another\ntypesafeai\n",
    )
    assert read_watchlist(path) == ["omarsar0", "typesafeai"]


def test_comment_only_watchlist_returns_empty_list(tmp_path: Path) -> None:
    """F2: a comment-only file yields `[]`."""
    path = _write(tmp_path / "watchlist.md", "# a\n# b\n   \n")
    assert read_watchlist(path) == []


def test_leading_at_and_surrounding_whitespace_stripped(tmp_path: Path) -> None:
    """F3: strip whitespace, then one leading `@`."""
    path = _write(tmp_path / "watchlist.md", "  @omarsar0 \n\ttypesafeai\t\n")
    assert read_watchlist(path) == ["omarsar0", "typesafeai"]


def test_only_one_leading_at_stripped(tmp_path: Path) -> None:
    """F3: only a single leading `@` is removed."""
    path = _write(tmp_path / "watchlist.md", "@@omarsar0\n")
    assert read_watchlist(path) == ["@omarsar0"]


def test_comment_with_leading_whitespace_ignored(tmp_path: Path) -> None:
    """F4: `   # paused` is a comment, same as a blank line."""
    path = _write(tmp_path / "watchlist.md", "   # paused\n\t# tabbed\nomarsar0\n")
    assert read_watchlist(path) == ["omarsar0"]


def test_duplicates_deduped_first_occurrence_order_kept(tmp_path: Path) -> None:
    """F5: duplicates (even `@`-prefixed) collapse; each handle fetched once."""
    path = _write(
        tmp_path / "watchlist.md",
        "omarsar0\ntypesafeai\n@omarsar0\nomarsar0\nSakanaAILabs\n",
    )
    assert read_watchlist(path) == ["omarsar0", "typesafeai", "SakanaAILabs"]


def test_illegal_handle_characters_pass_through(tmp_path: Path) -> None:
    """F6: M1 never silently drops a non-blank, non-comment line."""
    path = _write(tmp_path / "watchlist.md", "user!x\na/b\ntwo words\nomarsar0\n")
    assert read_watchlist(path) == ["user!x", "a/b", "two words", "omarsar0"]


def test_crlf_and_bom_handled(tmp_path: Path) -> None:
    """F7: CRLF endings and a UTF-8 BOM leave no `\\r` or `\\ufeff` residue."""
    raw = "\ufeffomarsar0\r\ntypesafeai\r\n# c\r\n\r\n"
    path = tmp_path / "watchlist.md"
    path.write_bytes(raw.encode("utf-8"))
    assert read_watchlist(path) == ["omarsar0", "typesafeai"]


def test_large_watchlist_preserves_order_without_truncation(tmp_path: Path) -> None:
    """F8: ~500 handles all come back in file order."""
    handles = [f"user{i:04d}" for i in range(500)]
    path = _write(tmp_path / "watchlist.md", "\n".join(handles) + "\n")
    assert read_watchlist(path) == handles


def test_unreadable_watchlist_aborts_naming_the_path(tmp_path: Path) -> None:
    """F10: no fallback to seeds; the error names the watchlist path."""
    path = _write(tmp_path / "watchlist.md", "omarsar0\n")
    if os.geteuid() == 0:  # root bypasses permission bits
        pytest.skip("permission bits do not apply to root")
    path.chmod(0o000)
    try:
        with pytest.raises(OSError) as excinfo:
            read_watchlist(path)
    finally:
        path.chmod(0o644)
    assert str(path) in str(excinfo.value)


def test_watchlist_path_is_directory_aborts_naming_the_path(tmp_path: Path) -> None:
    """F11: a directory at the watchlist path errors; no fallback, no state write."""
    with pytest.raises(OSError) as excinfo:
        read_watchlist(tmp_path)
    assert str(tmp_path) in str(excinfo.value)
