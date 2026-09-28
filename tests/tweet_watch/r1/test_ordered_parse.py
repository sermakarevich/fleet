"""R1 ensure_watchlist: returns the ordered handle list via M1 parse rules."""

from __future__ import annotations

from pathlib import Path

from fleet.tweet_watch.worker import ensure_watchlist


def test_comments_blanks_and_at_signs_are_normalized(tmp_path: Path) -> None:
    path = tmp_path / "watchlist.md"
    path.write_text(
        "# my list\n\n@omarsar0\ntypesafeai\n\n   # indented comment\n@cloneisjun\n",
        encoding="utf-8",
    )
    assert ensure_watchlist(path) == ["omarsar0", "typesafeai", "cloneisjun"]


def test_handle_case_and_order_are_preserved(tmp_path: Path) -> None:
    path = tmp_path / "watchlist.md"
    path.write_text("SakanaAILabs\nomarsar0\n", encoding="utf-8")
    assert ensure_watchlist(path) == ["SakanaAILabs", "omarsar0"]
