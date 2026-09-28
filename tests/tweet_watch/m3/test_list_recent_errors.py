"""M3 list_recent: external errors and scale (F12-F14)."""

from __future__ import annotations

import builtins
import os
import time
from datetime import date
from pathlib import Path

import pytest

from fleet.tweet_watch.reply_files import list_recent

RUN_DATE = date(2026, 9, 26)

needs_posix_perms = pytest.mark.skipif(
    os.geteuid() == 0 if hasattr(os, "geteuid") else True,
    reason="permission bits do not apply to root",
)


@needs_posix_perms
def test_unreadable_dir_aborts_naming_dir(tmp_path: Path) -> None:
    # F13: fail closed — never fall back to [] (that would disable dedupe).
    replies = tmp_path / "replies"
    replies.mkdir()
    (replies / "2026-09-26-1.md").write_text("body", encoding="utf-8")
    replies.chmod(0o000)
    try:
        with pytest.raises(Exception) as excinfo:
            list_recent(replies, RUN_DATE)
    finally:
        replies.chmod(0o755)
    assert str(replies) in str(excinfo.value)


@needs_posix_perms
def test_unreadable_in_window_file_aborts_naming_file(tmp_path: Path) -> None:
    # F14: silently skipping one file could re-propose its wording.
    replies = tmp_path / "replies"
    replies.mkdir()
    bad = replies / "2026-09-26-1.md"
    bad.write_text("body", encoding="utf-8")
    bad.chmod(0o000)
    try:
        with pytest.raises(Exception) as excinfo:
            list_recent(replies, RUN_DATE)
    finally:
        bad.chmod(0o644)
    assert "2026-09-26-1.md" in str(excinfo.value)


def test_unreadable_out_of_window_file_does_not_abort(tmp_path: Path) -> None:
    # Only in-window files are opened (F12/F14): an unreadable stale file
    # must not fail the run.
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        pytest.skip("permission bits do not apply to root")
    replies = tmp_path / "replies"
    replies.mkdir()
    stale = replies / "2026-01-01-9.md"
    stale.write_text("body", encoding="utf-8")
    stale.chmod(0o000)
    (replies / "2026-09-26-1.md").write_text("body", encoding="utf-8")
    try:
        got = {p.name for p in list_recent(replies, RUN_DATE)}
    finally:
        stale.chmod(0o644)
    assert got == {"2026-09-26-1.md"}


def test_large_backlog_filters_by_prefix(tmp_path: Path) -> None:
    # F12: scan filters by filename prefix; only in-window files are opened.
    replies = tmp_path / "replies"
    replies.mkdir()
    for i in range(500):
        (replies / f"2026-01-{(i % 28) + 1:02d}-{i}.md").write_text("stale", encoding="utf-8")
    (replies / "2026-09-26-aaa.md").write_text("new", encoding="utf-8")
    (replies / "2026-09-24-bbb.md").write_text("new", encoding="utf-8")
    start = time.monotonic()
    got = {p.name for p in list_recent(replies, RUN_DATE)}
    assert time.monotonic() - start < 10
    assert got == {"2026-09-26-aaa.md", "2026-09-24-bbb.md"}


def test_large_backlog_opens_only_in_window_bodies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # F12: bodies outside the window are never opened.
    replies = tmp_path / "replies"
    replies.mkdir()
    for i in range(100):
        (replies / f"2026-01-{(i % 28) + 1:02d}-{i}.md").write_text("stale", encoding="utf-8")
    (replies / "2026-09-26-aaa.md").write_text("new", encoding="utf-8")
    opened: list[str] = []
    real_open = builtins.open

    def counting_open(file, *args, **kwargs):  # type: ignore[no-untyped-def]
        if isinstance(file, (str, os.PathLike)) and str(file).startswith(str(replies)):
            opened.append(Path(file).name)
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", counting_open)
    list_recent(replies, RUN_DATE)
    out_of_window = [n for n in opened if n.startswith("2026-01-")]
    assert out_of_window == []
