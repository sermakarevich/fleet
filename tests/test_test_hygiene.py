"""Tests for test-suite hygiene rules (Clean 29/30, ADR 0006).

Pins the three rules a test can enforce: no test file grows past 600
lines (split by behaviour area instead), no test patches a private name
(use the injection seams: queue, store, runner, clock, api), and every
test module names its unit under test in its module docstring.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

TESTS_ROOT = Path(__file__).parent
MAX_TEST_FILE_LINES = 600

_PRIVATE_SETATTR = re.compile(r"setattr\s*\([^)]*['\"][_]")
_PRIVATE_PATCH = re.compile(r"""patch\s*\(\s*['"][^'"]*\._""")


def _test_modules() -> list[Path]:
    """Every test module the rules apply to (test_*.py plus conftests)."""
    return sorted(TESTS_ROOT.rglob("test_*.py")) + sorted(TESTS_ROOT.rglob("conftest.py"))


def test_no_test_file_over_600_lines() -> None:
    """Split files over 600 lines by behaviour area; keep them split."""
    offenders = [
        str(p.relative_to(TESTS_ROOT))
        for p in _test_modules()
        if len(p.read_text().splitlines()) > MAX_TEST_FILE_LINES
    ]
    assert not offenders, f"split these test files by behaviour area: {offenders}"


def test_no_private_name_patching() -> None:
    """No monkeypatch.setattr/patch of a name starting with _ (use the seams)."""
    offenders: list[str] = []
    for path in _test_modules():
        text = path.read_text()
        if _PRIVATE_SETATTR.search(text) or _PRIVATE_PATCH.search(text):
            offenders.append(str(path.relative_to(TESTS_ROOT)))
    assert not offenders, f"use injection seams instead of patching privates: {offenders}"


def test_every_test_module_has_a_docstring() -> None:
    """Every test module docstring names the unit under test."""
    offenders = [
        str(p.relative_to(TESTS_ROOT))
        for p in _test_modules()
        if not (ast.get_docstring(ast.parse(p.read_text())) or "").strip()
    ]
    assert not offenders, f"add a module docstring naming the unit under test: {offenders}"


def test_sleep_budget() -> None:
    """At most 10 raw sleeps outside tests/helpers, each with a why-comment."""
    offenders: list[str] = []
    for path in _test_modules():
        if "helpers" in path.parts:
            continue
        for i, line in enumerate(path.read_text().splitlines(), start=1):
            if re.search(r"(?<!\w)(time|asyncio)\.sleep\s*\(", line):
                offenders.append(f"{path.relative_to(TESTS_ROOT)}:{i}:{line.strip()}")
    assert len(offenders) <= 10, f"replace sleeps with wait_until/FakeClock: {offenders}"


def test_telegram_package_has_no_monkeypatch() -> None:
    """Telegram tests inject FakeTelegramApi (no monkeypatch storms)."""
    offenders = [
        str(p.relative_to(TESTS_ROOT))
        for p in (TESTS_ROOT / "integrations" / "telegram").glob("test_*.py")
        if "monkeypatch." in p.read_text()
    ]
    assert not offenders, f"inject fakes instead of monkeypatching: {offenders}"
