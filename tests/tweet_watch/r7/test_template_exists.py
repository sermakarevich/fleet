"""R7 template presence (F1): the file must exist at the documented path."""

from __future__ import annotations

from tests.tweet_watch.r7.conftest import TEMPLATE_PATH, template_text


def test_template_file_exists_at_documented_path() -> None:
    assert TEMPLATE_PATH.is_file(), (
        f"worker template missing at {TEMPLATE_PATH}: a missing template is "
        "a hard stop, never 'follow R1-R6 from memory' (R7-F1)"
    )


def test_template_is_nonempty() -> None:
    assert template_text().strip() != ""
