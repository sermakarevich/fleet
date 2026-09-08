"""Shared fixtures for ask_human store tests (ADR 0006 bead 11)."""

from __future__ import annotations

from pathlib import Path

import pytest

from fleet.integrations.ask_human.store import QuestionStore


@pytest.fixture
def question_store(tmp_path: Path) -> QuestionStore:
    """Fresh QuestionStore on a temp DB — no module global to monkeypatch."""
    return QuestionStore(tmp_path / "questions.db")
