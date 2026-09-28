"""R8 KB paths (F3, F8, F20): exact paths, never committed, parent-dir recovery."""

from fleet.tweet_watch.worker import (
    INTERESTS_PATH,
    REPLIES_DIR,
    STATE_PATH,
    WATCHLIST_PATH,
)


def test_watchlist_path_exact(runbook_text: str) -> None:
    assert str(WATCHLIST_PATH) in runbook_text


def test_state_path_exact(runbook_text: str) -> None:
    assert str(STATE_PATH) in runbook_text


def test_interests_path_exact(runbook_text: str) -> None:
    assert str(INTERESTS_PATH) in runbook_text


def test_replies_dir_exact(runbook_text: str) -> None:
    assert str(REPLIES_DIR) in runbook_text


def test_kb_files_never_committed(runbook_lower: str) -> None:
    assert "never commit" in runbook_lower


def test_no_git_add_of_kb_files(runbook_lower: str) -> None:
    assert "written directly" in runbook_lower or "never committed" in runbook_lower


def test_missing_parent_dir_routes_through_ensure(runbook_text: str) -> None:
    assert "mkdir -p" in runbook_text
    assert str(WATCHLIST_PATH) in runbook_text or "watchlist" in runbook_text.lower()
