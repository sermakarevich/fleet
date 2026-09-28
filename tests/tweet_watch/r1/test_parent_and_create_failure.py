"""R1 ensure_watchlist: missing parent is created (F8); failed create aborts (F9)."""

from __future__ import annotations

from pathlib import Path

import pytest

from fleet.tweet_watch.kb_files import SEED_HANDLES
from fleet.tweet_watch.worker import ensure_watchlist


def test_missing_parent_dirs_are_created(tmp_path: Path) -> None:
    path = tmp_path / "media" / "x" / "watchlist.md"
    assert not path.parent.exists()
    assert ensure_watchlist(path) == list(SEED_HANDLES)
    assert path.read_text(encoding="utf-8").splitlines() == list(SEED_HANDLES)


def test_create_failure_aborts_naming_the_path(tmp_path: Path) -> None:
    blocker = tmp_path / "blocker"
    blocker.write_text("not a dir", encoding="utf-8")
    path = blocker / "watchlist.md"
    with pytest.raises(Exception) as excinfo:  # noqa: BLE001, PT011
        ensure_watchlist(path)
    assert str(path) in str(excinfo.value)
    assert not (tmp_path / "watch_state.json").exists()
