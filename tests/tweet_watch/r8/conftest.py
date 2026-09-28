"""Shared fixtures for R8 runbook tests.

The unit under test is the repo file ``docs/tweet_watch/RUNBOOK.md``.
These fixtures locate it relative to the repo root and expose its text,
plus the real scaffold path constants the runbook must document exactly.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fleet.tweet_watch.worker import (
    INTERESTS_PATH,
    REPLIES_DIR,
    STATE_PATH,
    WATCHLIST_PATH,
)

RUNBOOK_PATH = Path(__file__).resolve().parents[3] / "docs" / "tweet_watch" / "RUNBOOK.md"


@pytest.fixture(scope="session")
def runbook_path() -> Path:
    return RUNBOOK_PATH


@pytest.fixture(scope="session")
def runbook_text(runbook_path: Path) -> str:
    if not runbook_path.is_file():
        raise FileNotFoundError(f"runbook missing at {runbook_path}")
    return runbook_path.read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def runbook_lower(runbook_text: str) -> str:
    return runbook_text.lower()


@pytest.fixture(scope="session")
def scaffold_paths() -> dict[str, str]:
    return {
        "watchlist": str(WATCHLIST_PATH),
        "state": str(STATE_PATH),
        "interests": str(INTERESTS_PATH),
        "replies": str(REPLIES_DIR),
    }
