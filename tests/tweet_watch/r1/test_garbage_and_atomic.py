"""R1 ensure_watchlist: garbage passes through unrepaired (F11); seeds write atomically (F12)."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from fleet.tweet_watch.worker import ensure_watchlist


def test_garbage_lines_are_not_repaired_or_reseeded(tmp_path: Path) -> None:
    content = b"user!x\nbad handle\n\n# comment\n"
    path = tmp_path / "watchlist.md"
    path.write_bytes(content)
    result = ensure_watchlist(path)
    assert "user!x" in result
    assert path.read_bytes() == content


def test_successful_create_leaves_no_temp_files(tmp_path: Path) -> None:
    parent = tmp_path / "x"
    parent.mkdir()
    ensure_watchlist(parent / "watchlist.md")
    assert sorted(p.name for p in parent.iterdir()) == ["watchlist.md"]


def test_killed_seed_write_leaves_no_half_written_file(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "watchlist.md"
    attempts: list[tuple] = []

    def boom(*args, **kwargs):
        attempts.append(args)
        raise OSError("simulated kill mid-write")

    monkeypatch.setattr(os, "replace", boom)
    monkeypatch.setattr(os, "rename", boom)
    monkeypatch.setattr(Path, "rename", boom)
    monkeypatch.setattr(shutil, "move", boom)
    with pytest.raises(Exception):  # noqa: BLE001, B017, PT011
        ensure_watchlist(path)
    assert attempts, "seed write must go through atomic temp file + rename (F12)"
    assert not path.exists()
