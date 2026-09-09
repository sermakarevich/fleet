"""Shared fixtures and helpers for CLI tests."""

from __future__ import annotations

from typer.testing import CliRunner

# ---------------------------------------------------------------------------
# Shared by test_cli.py splits (Clean 29/30: moved, not rewritten).
# ---------------------------------------------------------------------------

runner = CliRunner()
