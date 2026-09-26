"""R8 runbook presence (F1): the file exists at the documented path and is usable."""

from pathlib import Path


def test_runbook_exists_at_documented_path(runbook_path: Path) -> None:
    assert runbook_path.is_file(), f"runbook missing at {runbook_path}"
    assert str(runbook_path).endswith("docs/tweet_watch/RUNBOOK.md")


def test_runbook_is_nonempty_markdown(runbook_text: str) -> None:
    assert len(runbook_text.strip()) > 0
    assert runbook_text.lstrip().startswith("#")


def test_runbook_names_its_own_path(runbook_text: str) -> None:
    assert "docs/tweet_watch/RUNBOOK.md" in runbook_text
