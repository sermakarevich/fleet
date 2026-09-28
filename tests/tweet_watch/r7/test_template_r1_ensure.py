"""R7 template R1 ensure step (F2) and parent-dir creation (F19).

The template must tell the worker to create the watchlist with the exact 5
seed handles when missing, and to ``mkdir -p`` the KB parent dir. Seed
handles come from the real scaffold object so template and code cannot
drift.
"""

from __future__ import annotations

import pytest

from fleet.tweet_watch.kb_files import SEED_HANDLES
from fleet.tweet_watch.worker import WATCHLIST_PATH
from tests.tweet_watch.r7.conftest import template_text


@pytest.mark.parametrize("handle", list(SEED_HANDLES))
def test_template_names_each_seed_handle(handle: str) -> None:
    assert handle in template_text(), (
        f"template omits seed handle {handle!r}: a worker finding no "
        "watchlist must never invent seeds (R7-F2)"
    )


def test_template_states_create_if_missing() -> None:
    assert "if missing" in template_text().lower(), (
        "template omits the R1 ensure step (create watchlist if missing)"
    )


def test_template_names_watchlist_path_from_scaffold() -> None:
    assert str(WATCHLIST_PATH) in template_text()


def test_template_instructs_mkdir_p_for_parent_dir() -> None:
    assert "mkdir -p" in template_text(), (
        "template must instruct mkdir -p via the R1 ensure path when "
        "media/x/ itself is absent (R7-F19)"
    )
