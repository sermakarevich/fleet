"""Pins the ADR 0006 tooling gate: just recipes exist, dead settings are gone."""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

REQUIRED_RECIPES = {"check", "lint", "fmt-check", "typecheck", "ui-build"}


def _recipe_names(justfile_text: str) -> set[str]:
    """Recipe names declared in a justfile (one `name:` per line, no indent)."""
    names = set()
    for line in justfile_text.splitlines():
        match = re.match(r"^([A-Za-z0-9_-]+)\s*:", line)
        if match:
            names.add(match.group(1))
    return names


def test_justfile_declares_check_gate_recipes() -> None:
    """justfile must declare every recipe the check gate needs."""
    names = _recipe_names((REPO_ROOT / "justfile").read_text(encoding="utf-8"))
    assert names >= REQUIRED_RECIPES, f"missing recipes: {REQUIRED_RECIPES - names}"


def test_pyproject_has_no_dead_lint_settings() -> None:
    """pyproject must not silence lint (no --exit-zero, no E501 ignore)."""
    text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "--exit-zero" not in text
    assert "E501" not in text
