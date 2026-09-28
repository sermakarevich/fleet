"""R1 ensure_watchlist: directory path (F3) and unreadable file (F4) abort cleanly."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from fleet.tweet_watch.worker import ensure_watchlist


def test_watchlist_path_is_a_directory_aborts(tmp_path: Path) -> None:
    path = tmp_path / "watchlist.md"
    path.mkdir()
    with pytest.raises(Exception) as excinfo:  # noqa: BLE001, PT011
        ensure_watchlist(path)
    assert str(path) in str(excinfo.value)
    assert path.is_dir()
    assert not (tmp_path / "watch_state.json").exists()


def test_unreadable_watchlist_aborts_without_seed_fallback(tmp_path: Path) -> None:
    path = tmp_path / "watchlist.md"
    path.write_text("omarsar0\n", encoding="utf-8")
    try:
        with path.open("r", encoding="utf-8"):
            pass
    except OSError:
        pytest.skip("cannot make file unreadable in this environment")
    os.chmod(path, 0)
    try:
        with path.open("r", encoding="utf-8"):
            pytest.skip("file still readable (e.g. running as root)")
    except OSError:
        pass
    try:
        with pytest.raises(Exception) as excinfo:  # noqa: BLE001, PT011
            ensure_watchlist(path)
        assert str(path) in str(excinfo.value)
    finally:
        os.chmod(path, 0o600)
    assert not (tmp_path / "watch_state.json").exists()
