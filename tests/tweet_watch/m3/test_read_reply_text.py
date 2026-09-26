"""M3 read_reply_text: body extraction (F5-F7, F18-F19)."""

from __future__ import annotations

from pathlib import Path

from fleet.tweet_watch.reply_files import read_reply_text

SAMPLE = """# @sermakarevich — 2026-09-26T10:00:00+00:00

> source: https://x.com/sermakarevich/status/2103871751771898112

> reply to: 2103870000000000000

@omarsar0 A harness is just a loop around tool calls; the loop is the product.

likes 5 · retweets 0 · replies 1 · views 245
"""


def _write(replies: Path, name: str, data: bytes) -> Path:
    p = replies / name
    p.write_bytes(data)
    return p


def test_reads_body_text_from_repo_format(tmp_path: Path) -> None:
    replies = tmp_path / "replies"
    replies.mkdir()
    p = _write(replies, "2026-09-26-1.md", SAMPLE.encode("utf-8"))
    text = read_reply_text(p)
    assert "harness is just a loop" in text


def test_empty_file_yields_empty_text(tmp_path: Path) -> None:
    # F5: truncated/empty file contributes nothing but does not abort.
    replies = tmp_path / "replies"
    replies.mkdir()
    p = _write(replies, "2026-09-26-1.md", b"")
    assert read_reply_text(p) == ""


def test_format_drift_still_read(tmp_path: Path) -> None:
    # F6: M3 never rejects a file for format drift on read.
    replies = tmp_path / "replies"
    replies.mkdir()
    p = _write(
        replies,
        "2026-09-26-1.md",
        "# hand-edited note\n\njust a plain body line\n".encode("utf-8"),
    )
    assert "just a plain body line" in read_reply_text(p)


def test_unicode_body_verbatim(tmp_path: Path) -> None:
    # F7: emoji / CJK / multi-line quotes survive as decoded text.
    replies = tmp_path / "replies"
    replies.mkdir()
    body = "@user  кораблей 🚀 循环 har—ness\n> quoted line one\n> quoted line two\n"
    p = _write(replies, "2026-09-26-1.md", body.encode("utf-8"))
    assert read_reply_text(p) == body


def test_corrupt_body_best_effort(tmp_path: Path) -> None:
    # F18: binary garbage reads best-effort, never raises, never deleted.
    replies = tmp_path / "replies"
    replies.mkdir()
    p = _write(replies, "2026-09-26-1.md", b"\xff\xfe\x00binary \x80garbage\n")
    text = read_reply_text(p)
    assert isinstance(text, str)
    assert "binary" in text
    assert p.exists()


def test_hand_edited_content_reported_as_is(tmp_path: Path) -> None:
    # F19: M3 has no ground truth; dedupe compares against the files.
    replies = tmp_path / "replies"
    replies.mkdir()
    p = _write(
        replies, "2026-09-26-1.md", "edited after posting\n".encode("utf-8")
    )
    assert read_reply_text(p) == "edited after posting\n"
