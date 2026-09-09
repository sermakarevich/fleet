"""Shared fixtures and helpers for coder tests."""

from __future__ import annotations

from fleet.coders.claude import ClaudeCoder
from fleet.state.paths import fleet_home

# ---------------------------------------------------------------------------
# Shared by test_coder_claude.py splits (Clean 29/30: moved, not rewritten).
# ---------------------------------------------------------------------------


def _coder() -> ClaudeCoder:
    return ClaudeCoder(fleet_home=fleet_home())
