"""Tests for the read_file template global in fleet.flows.templates."""

from __future__ import annotations

from pathlib import Path

import pytest

from fleet.core.errors import TemplateError
from fleet.flows import templates


def test_read_file_returns_utf8_text(tmp_path: Path) -> None:
    """An absolute path renders the file's text content."""
    target = tmp_path / "kb.md"
    target.write_text("knowledge: hello\n", encoding="utf-8")
    assert templates.render(f"{{{{ read_file({str(target)!r}) }}}}", {}) == "knowledge: hello\n"


def test_read_file_relative_path_rejected() -> None:
    """A relative path raises naming the path."""
    with pytest.raises(TemplateError, match="read_file: path must be absolute"):
        templates.render("{{ read_file('docs/kb.md') }}", {})


def test_read_file_missing_file_error(tmp_path: Path) -> None:
    """A missing absolute path raises a cannot-read error."""
    missing = tmp_path / "absent.md"
    with pytest.raises(TemplateError, match="read_file: cannot read"):
        templates.render(f"{{{{ read_file({str(missing)!r}) }}}}", {})


def test_read_file_size_limit(tmp_path: Path) -> None:
    """Files larger than READ_FILE_MAX_BYTES are rejected."""
    assert templates.READ_FILE_MAX_BYTES == 200_000
    target = tmp_path / "big.md"
    target.write_bytes(b"x" * (templates.READ_FILE_MAX_BYTES + 1))
    with pytest.raises(TemplateError, match="is larger than 200000 bytes"):
        templates.render(f"{{{{ read_file({str(target)!r}) }}}}", {})


def test_sandbox_still_blocks_attribute_escapes(tmp_path: Path) -> None:
    """Dunder access fails as before; read_file is the only filesystem path."""
    target = tmp_path / "kb.md"
    target.write_text("hi", encoding="utf-8")
    with pytest.raises(TemplateError):
        templates.render("{{ ''.__class__ }}", {})
    with pytest.raises(TemplateError):
        templates.render("{{ read_file.__class__ }}", {})
    with pytest.raises(TemplateError):
        templates.render(f"{{{{ open({str(target)!r}) }}}}", {})
