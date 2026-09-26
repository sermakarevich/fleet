"""M3 reply-files: read/write per-tweet reply files."""

from __future__ import annotations

import os
import re
import tempfile
from datetime import date, timedelta
from pathlib import Path

_FILENAME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-(.+)\.md$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_STATS_RE = re.compile(r"likes \d+ · retweets \d+ · replies \d+ · views \d+")


def _filename_date(name: str) -> date | None:
    match = _FILENAME_RE.match(name)
    if match is None:
        return None
    try:
        parsed = date.fromisoformat(match.group(1))
    except ValueError:
        return None
    if parsed.isoformat() != match.group(1):
        return None
    return parsed


def _readable(path: Path) -> bool:
    try:
        mode = path.stat().st_mode
    except OSError:
        return False
    if mode & 0o444 == 0:
        return False
    return os.access(path, os.R_OK)


def list_recent(replies_dir: Path, today: date, window_days: int = 3) -> list[Path]:
    """List in-window reply files.

    Returns ``<date>-<id>.md`` files whose filename date prefix is within
    ``today - window_days <= file_date <= today`` (inclusive, calendar
    dates; filename prefix wins over mtime; future-dated files excluded).
    A missing dir or an empty window returns ``[]``; non-``.md`` or
    undateable filenames are ignored; only in-window bodies are opened.
    An unreadable dir or in-window file aborts with an error naming the
    path (fail closed, never fall back to ``[]``).
    """
    directory = Path(replies_dir)
    if not directory.exists():
        return []
    if directory.stat().st_mode & 0o555 == 0 or not os.access(
        directory, os.R_OK | os.X_OK
    ):
        raise OSError(f"{directory}: replies dir is not readable")
    try:
        entries = sorted(directory.iterdir(), key=lambda p: p.name)
    except OSError as exc:
        raise OSError(f"{directory}: cannot list replies dir: {exc}") from exc
    start = today - timedelta(days=window_days)
    recent: list[Path] = []
    for entry in entries:
        if not entry.name.endswith(".md") or not entry.is_file():
            continue
        file_date = _filename_date(entry.name)
        if file_date is None or not start <= file_date <= today:
            continue
        try:
            with entry.open("rb") as handle:
                handle.read(1)
        except OSError as exc:
            raise OSError(f"{entry}: cannot read reply file: {exc}") from exc
        if not _readable(entry):
            raise OSError(f"{entry}: cannot read reply file: permission denied")
        recent.append(entry)
    return recent


def _is_boilerplate(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return True
    if stripped.startswith("#"):
        return True
    lowered = stripped.lower()
    if lowered.startswith("> source:") or lowered.startswith("> reply to:"):
        return True
    if _STATS_RE.search(stripped) is not None:
        return True
    return False


def read_reply_text(reply_path: Path) -> str:
    """Read one reply file's comparable text.

    Decodes as UTF-8 best-effort (``errors="replace"``); empty or
    boilerplate-only files yield ``""``; never rejects a file for format
    drift — comparison uses whatever body text is present.
    """
    raw = Path(reply_path).read_bytes()
    text = raw.decode("utf-8", errors="replace")
    if not text.strip():
        return ""
    if all(_is_boilerplate(line) for line in text.splitlines()):
        return ""
    return text


def _check_post_date(post_date: str) -> None:
    if not isinstance(post_date, str) or _DATE_RE.match(post_date) is None:
        raise ValueError(f"invalid post date {post_date!r}: expected YYYY-MM-DD")
    try:
        parsed = date.fromisoformat(post_date)
    except ValueError:
        raise ValueError(
            f"invalid post date {post_date!r}: expected YYYY-MM-DD"
        ) from None
    if parsed.isoformat() != post_date:
        raise ValueError(f"invalid post date {post_date!r}: expected YYYY-MM-DD")


def _check_reply_id(reply_id: str) -> None:
    if not isinstance(reply_id, str) or not reply_id.strip():
        raise ValueError(f"invalid reply id {reply_id!r}: expected non-empty id")
    if "/" in reply_id or "\\" in reply_id or reply_id.strip() in (".", ".."):
        raise ValueError(
            f"invalid reply id {reply_id!r}: must be a plain filename segment"
        )


def write_reply(
    replies_dir: Path, post_date: str, reply_id: str, content: str
) -> Path:
    """Write ``<date>-<id>.md`` in the existing per-tweet format.

    Validates ``post_date`` (``YYYY-MM-DD``) and ``reply_id`` (non-empty)
    before touching the filesystem; ``mkdir -p`` the dir; writes the
    per-tweet format (header, ``> source:``, ``> reply to:``, body, stats
    line) atomically via temp file plus rename; overwrites an existing
    same-path file idempotently (no ``-2`` duplicates).
    """
    _check_post_date(post_date)
    _check_reply_id(reply_id)
    directory = Path(replies_dir)
    target = directory / f"{post_date}-{reply_id}.md"
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise OSError(f"{target}: cannot create replies dir: {exc}") from exc
    body = content if content.endswith("\n") else content + "\n"
    text = (
        f"# Reply {reply_id} — {post_date}\n"
        f"\n"
        f"> source: https://x.com/i/status/{reply_id}\n"
        f"\n"
        f"> reply to: {reply_id}\n"
        f"\n"
        f"{body}"
        f"\n"
        f"likes 0 · retweets 0 · replies 0 · views 0\n"
    )
    try:
        fd, tmp_name = tempfile.mkstemp(
            dir=str(directory), prefix=target.name + ".", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as tmp_file:
                tmp_file.write(text)
            os.replace(tmp_name, target)
        except BaseException:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise
    except OSError as exc:
        if str(target.name) in str(exc):
            raise
        raise OSError(f"{target}: cannot persist reply: {exc}") from exc
    return target
