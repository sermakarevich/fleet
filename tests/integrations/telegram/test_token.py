"""Tests for `telegram_token`: env var, then file fallback, then ''."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from fleet.integrations.telegram.token import telegram_token


@pytest.fixture(autouse=True)
def _clean_env() -> Iterator[None]:
    saved = os.environ.pop("TELEGRAM_BOT_TOKEN", None)
    try:
        yield
    finally:
        if saved is not None:
            os.environ["TELEGRAM_BOT_TOKEN"] = saved
        else:
            os.environ.pop("TELEGRAM_BOT_TOKEN", None)


def test_env_var_wins_over_file(tmp_path: Path) -> None:
    (tmp_path / "telegram_token").write_text("file-token\n")
    os.environ["TELEGRAM_BOT_TOKEN"] = "env-token"
    assert telegram_token(tmp_path) == "env-token"


def test_file_used_when_env_empty(tmp_path: Path) -> None:
    (tmp_path / "telegram_token").write_text("file-token\n")
    assert telegram_token(tmp_path) == "file-token"


def test_empty_when_neither_present(tmp_path: Path) -> None:
    assert telegram_token(tmp_path) == ""
