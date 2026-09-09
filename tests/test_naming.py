"""Naming invariants from ADR 0006 rule 4 (Clean 19/30).

One word per concept means no private cross-module imports and no
single-letter public parameters. Both are checked with ``ast`` so a
rename that reintroduces either fails here, not in review.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).parent.parent / "src" / "fleet"

# Single-letter params allowed only as math coordinates in this module.
MATH_EXCEPTION = ("core/context_window.py", ("x", "y", "n"))


def _modules() -> list[Path]:
    return sorted(SRC.rglob("*.py"))


def _module_name(path: Path) -> str:
    return ".".join(path.relative_to(SRC).with_suffix("").parts)


def test_no_private_cross_module_imports() -> None:
    """No module in src/fleet imports an underscore name from another module."""
    violations: list[str] = []
    for path in _modules():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        here = _module_name(path)
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            source = ("." * node.level) + (node.module or "")
            for alias in node.names:
                if not alias.name.startswith("_"):
                    continue
                if source.rstrip(".") in ("", "."):
                    continue
                # Same-module relative import (e.g. `from . import x`) is fine.
                violations.append(f"{here}:{node.lineno} imports {alias.name} from {source}")
    assert violations == [], "\n".join(violations)


def test_no_single_letter_public_params() -> None:
    """No public function parameter is a single letter.

    Excepted: x, y, n as math coordinates in core/context_window.py.
    """
    violations: list[str] = []
    for path in _modules():
        rel = str(path.relative_to(SRC))
        allowed = MATH_EXCEPTION[1] if rel == MATH_EXCEPTION[0] else ()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if node.name.startswith("_"):
                continue
            params = list(node.args.posonlyargs) + list(node.args.args) + list(node.args.kwonlyargs)
            for arg in params:
                if arg.arg in ("self", "cls"):
                    continue
                if len(arg.arg) == 1 and arg.arg not in allowed:
                    violations.append(f"{rel}:{node.lineno} {node.name}({arg.arg})")
    assert violations == [], "\n".join(violations)
