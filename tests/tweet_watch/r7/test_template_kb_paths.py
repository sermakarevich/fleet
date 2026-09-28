"""R7 template KB paths (F3) and no-commit rule (F10).

The template must name the exact absolute KB paths (taken from the real
scaffold constants) and must never instruct committing KB files to the repo.
"""

from __future__ import annotations

import pytest

from fleet.tweet_watch.worker import (
    INTERESTS_PATH,
    REPLIES_DIR,
    STATE_PATH,
    WATCHLIST_PATH,
)
from tests.tweet_watch.r7.conftest import template_text


@pytest.mark.parametrize(
    "path",
    [str(WATCHLIST_PATH), str(STATE_PATH), str(INTERESTS_PATH), str(REPLIES_DIR)],
)
def test_template_names_exact_kb_path(path: str) -> None:
    assert path in template_text(), (
        f"template must name the exact KB path {path}: the worker never "
        "falls back to a 'likely' path (R7-F3)"
    )


def test_template_does_not_instruct_committing_kb_files() -> None:
    assert "git add" not in template_text(), (
        "template must not instruct committing KB files; they are written "
        "directly and never committed (R7-F10)"
    )


def test_template_uses_absolute_kb_prefix_not_tilde() -> None:
    assert "~/.ai" not in template_text(), (
        "template must use the absolute /Users/sergii/.ai/... prefix (R7-F3)"
    )
