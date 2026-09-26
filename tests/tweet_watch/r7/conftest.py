"""Shared helpers for R7 worker-template tests.

R7's unit under test is the repo template file
``docs/tweet_watch/WORKER.md``, not Python code, so these helpers locate it
in the checkout and read it. Tests import the real scaffold path constants
and seed handles from ``fleet.tweet_watch`` so the template cannot drift
from the code: every exact KB path asserted below comes from the object the
worker itself uses.
"""

from __future__ import annotations

from pathlib import Path


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in (here.parent, *here.parents):
        if (parent / "pyproject.toml").is_file():
            return parent
    raise RuntimeError("repo root (pyproject.toml) not found above tests")


REPO_ROOT = _repo_root()
TEMPLATE_PATH = REPO_ROOT / "docs" / "tweet_watch" / "WORKER.md"


def template_text() -> str:
    """Read the worker template; a missing file fails the test (R7-F1)."""
    return TEMPLATE_PATH.read_text(encoding="utf-8")
