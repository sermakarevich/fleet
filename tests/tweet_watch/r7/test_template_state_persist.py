"""R7 template state persistence (F5) and corrupt-state handling (F21)."""

from __future__ import annotations

from fleet.tweet_watch.worker import STATE_PATH
from tests.tweet_watch.r7.conftest import template_text


def test_template_instructs_state_persist() -> None:
    assert "persist" in template_text().lower(), (
        "without the R2 write-back every run re-emits the same tweets "
        "(R7-F5)"
    )


def test_template_names_state_path_from_scaffold() -> None:
    assert str(STATE_PATH) in template_text()


def test_template_instructs_abort_on_corrupt_state() -> None:
    lowered = template_text().lower()
    assert "corrupt" in lowered or "invalid json" in lowered, (
        "template must instruct abort-before-fetch on corrupt state, never "
        "a silent reset to {} (R7-F21)"
    )
