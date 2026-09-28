"""R6 boundaries: F10 (midnight), F11 (idempotent retry), F12 (last text wins)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from fleet.tweet_watch.worker import parse_confirmation, persist_reply


def test_f10_date_is_confirmation_day_not_run_start_day() -> None:
    run_start = date(2026, 9, 26)
    confirm_day = date(2026, 9, 27)
    assert parse_confirmation("posted 2103871751771898112", run_start)[1] == "2026-09-26"
    assert parse_confirmation("posted 2103871751771898112", confirm_day)[1] == "2026-09-27"


def test_f11_reconfirm_same_id_overwrites_same_path(
    replies_dir: Path, source_url: str, source_body: str, posted_text: str
) -> None:
    first = persist_reply(source_url, source_body, posted_text, "123", "2026-09-26", replies_dir)
    second = persist_reply(source_url, source_body, posted_text, "123", "2026-09-26", replies_dir)
    assert first == second == replies_dir / "2026-09-26-123.md"
    assert [p.name for p in replies_dir.iterdir()] == ["2026-09-26-123.md"]
    assert "123" not in [p.stem for p in replies_dir.glob("*-2*")]


def test_f12_same_id_new_text_overwrites_with_new_text(
    replies_dir: Path, source_url: str, source_body: str
) -> None:
    persist_reply(
        source_url, source_body, "first confirmed wording", "123", "2026-09-26", replies_dir
    )
    target = persist_reply(
        source_url, source_body, "reposted with edits wording", "123", "2026-09-26", replies_dir
    )
    assert target == replies_dir / "2026-09-26-123.md"
    text = target.read_text(encoding="utf-8")
    assert "reposted with edits wording" in text
    assert [p.name for p in replies_dir.iterdir()] == ["2026-09-26-123.md"]
