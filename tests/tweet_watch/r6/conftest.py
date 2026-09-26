"""Shared fixtures for R6 reply-persistence tests."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

TODAY = date(2026, 9, 26)

SOURCE_URL = "https://x.com/typesafeai/status/2103871751771898101"
SOURCE_BODY = "We cut eval cost 10x with a verifier model gating releases."
POSTED_TEXT = (
    "@typesafeai A verifier model is a separate model that checks the main "
    "model's answer before release. Gating on it cut our bad deploys in half."
)
REPLY_ID = "2103871751771898112"


@pytest.fixture
def today() -> date:
    return TODAY


@pytest.fixture
def replies_dir(tmp_path: Path) -> Path:
    d = tmp_path / "replies"
    d.mkdir()
    return d


@pytest.fixture
def source_url() -> str:
    return SOURCE_URL


@pytest.fixture
def source_body() -> str:
    return SOURCE_BODY


@pytest.fixture
def posted_text() -> str:
    return POSTED_TEXT


@pytest.fixture
def reply_id() -> str:
    return REPLY_ID


def dir_snapshot(replies_dir: Path) -> set[str]:
    return {p.name for p in replies_dir.iterdir()} if replies_dir.exists() else set()
