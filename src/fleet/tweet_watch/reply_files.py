"""M3 reply-files: read/write per-tweet reply files (scaffold)."""

from __future__ import annotations

from datetime import date
from pathlib import Path


def list_recent(replies_dir: Path, today: date, window_days: int = 3) -> list[Path]:
    """SCAFFOLD (not implemented): list in-window reply files.

    Must do: return ``<date>-<id>.md`` files whose filename date prefix is
    within ``today - window_days <= file_date <= today`` (inclusive,
    calendar dates; filename prefix wins over mtime; future-dated files
    excluded); missing dir or empty window returns ``[]``; non-``.md`` or
    undateable filenames are ignored; only in-window bodies are opened
    later; unreadable dir or file aborts with an error naming the path
    (fail closed, never fall back to ``[]``).
    Serves: M3, needed by R4, R5, R6.
    Depends on: nothing (stdlib only).
    Depended on by: worker.run (recency dedupe input).
    """
    raise NotImplementedError


def read_reply_text(reply_path: Path) -> str:
    """SCAFFOLD (not implemented): read one reply file's comparable text.

    Must do: decode as UTF-8 best-effort (``errors="replace"``); empty or
    boilerplate-only files yield ``""``; never reject a file for format
    drift — comparison uses whatever body text is present.
    Serves: M3, needed by R4, R5, R6.
    Depends on: nothing (stdlib only).
    Depended on by: worker.run (recency dedupe input).
    """
    raise NotImplementedError


def write_reply(
    replies_dir: Path, post_date: str, reply_id: str, content: str
) -> Path:
    """SCAFFOLD (not implemented): write ``<date>-<id>.md`` in repo format.

    Must do: validate ``post_date`` is ``YYYY-MM-DD`` and ``reply_id`` is a
    non-empty id before touching the filesystem (error naming the bad
    value); ``mkdir -p`` the dir; write the existing per-tweet format
    (header, ``> source:``, ``> reply to:``, quoted body, stats line)
    atomically via temp file plus rename; overwrite an existing same-path
    file idempotently (no ``-2`` duplicates).
    Serves: M3, needed by R4, R5, R6.
    Depends on: nothing (stdlib only).
    Depended on by: worker.persist_reply.
    """
    raise NotImplementedError
