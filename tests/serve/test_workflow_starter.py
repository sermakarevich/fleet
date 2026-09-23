"""Tests for serve/app._workflow_starter (Telegram /workflow and /summary)."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from fleet.serve.app import _workflow_starter


def _state_no_workflow() -> MagicMock:
    """AppState double whose workflow store knows no workflow by name."""
    state = MagicMock()
    state.workflow_store.get_by_name.return_value = None
    return state


def test_workflow_starter_unknown_name_raises_not_imported() -> None:
    """Unknown workflow names raise ValueError mentioning `not imported`."""
    start = _workflow_starter(_state_no_workflow())
    with pytest.raises(ValueError, match="not imported"):
        asyncio.run(start("summarise", {"url": "https://e.com/a"}))
