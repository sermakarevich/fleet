"""R7 template concurrency: overlap semantics (F26) and racing writes (F27)."""

from __future__ import annotations

from tests.tweet_watch.r7.conftest import template_text


def test_template_states_overlap_semantics() -> None:
    lowered = template_text().lower()
    assert any(
        word in lowered for word in ("overlap", "concurrent", "collid")
    ), "overlapping runs may propose independently; no de-duping the other run (R7-F26)"


def test_template_forbids_lockfiles() -> None:
    assert "lock" in template_text().lower(), (
        "the template must not instruct lockfiles or state-file merges (R7-F26)"
    )


def test_template_states_idempotent_reply_writes() -> None:
    lowered = template_text().lower()
    assert "idempotent" in lowered or "same path" in lowered or "same-path" in lowered, (
        "double confirmation converges via idempotent same-path R6 writes (R7-F26)"
    )


def test_template_avoids_read_modify_write_index() -> None:
    lowered = template_text().lower()
    assert any(
        word in lowered for word in ("atomic", "rename", "one file per")
    ), "one file per reply, one rename per write; no index appends (R7-F27)"
