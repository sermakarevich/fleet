"""R1 ensure_watchlist: file lost between ensure and read aborts without retry loop (F10)."""

from __future__ import annotations

from pathlib import Path

import pytest

import fleet.tweet_watch.kb_files as kb_files
import fleet.tweet_watch.worker as worker_mod
from fleet.tweet_watch.worker import ensure_watchlist


def test_vanishing_file_aborts_naming_the_path(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "watchlist.md"
    path.write_text("omarsar0\n", encoding="utf-8")
    calls: list[int] = []

    def vanishing_read(read_path) -> list[str]:
        calls.append(1)
        try:
            Path(read_path).unlink()
        except FileNotFoundError:
            pass
        raise FileNotFoundError(f"watchlist vanished mid-run: {read_path}")

    monkeypatch.setattr(kb_files, "read_watchlist", vanishing_read)
    if hasattr(worker_mod, "read_watchlist"):
        monkeypatch.setattr(worker_mod, "read_watchlist", vanishing_read)
    with pytest.raises(Exception) as excinfo:  # noqa: BLE001, PT011
        ensure_watchlist(path)
    assert str(path) in str(excinfo.value)
    assert len(calls) <= 2
