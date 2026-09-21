"""Tests for locating INVESTIGATION.md (state/investigation.py)."""

from fleet.state.investigation import (
    INVESTIGATION_MD,
    REPORT_MAX_BYTES,
    read_report,
    report_path,
)
from fleet.state.paths import OUTPUTS_DIR


def test_report_in_artifacts_is_found(tmp_path):
    path = tmp_path / "artifacts" / INVESTIGATION_MD
    path.parent.mkdir(parents=True)
    path.write_text("## Root cause\n\nBy hand.\n", encoding="utf-8")
    assert report_path(tmp_path) == path
    text, found = read_report(tmp_path)
    assert found == path
    assert "By hand." in text


def test_report_in_outputs_is_found(tmp_path):
    path = tmp_path / OUTPUTS_DIR / INVESTIGATION_MD
    path.parent.mkdir(parents=True)
    path.write_text("## Root cause\n\nBy hand.\n", encoding="utf-8")
    assert report_path(tmp_path) == path
    assert read_report(tmp_path)[1] == path


def test_artifacts_wins_when_both_exist(tmp_path):
    artifacts = tmp_path / "artifacts" / INVESTIGATION_MD
    artifacts.parent.mkdir(parents=True)
    artifacts.write_text("from artifacts", encoding="utf-8")
    outputs = tmp_path / OUTPUTS_DIR / INVESTIGATION_MD
    outputs.parent.mkdir(parents=True)
    outputs.write_text("from outputs", encoding="utf-8")
    assert report_path(tmp_path) == artifacts
    assert read_report(tmp_path)[0] == "from artifacts"


def test_missing_file_returns_none(tmp_path):
    assert report_path(tmp_path) is None
    assert read_report(tmp_path) is None


def test_large_file_is_truncated_to_cap_bytes(tmp_path):
    path = tmp_path / "artifacts" / INVESTIGATION_MD
    path.parent.mkdir(parents=True)
    path.write_bytes(b"x" * (REPORT_MAX_BYTES + 100))
    text, found = read_report(tmp_path)
    assert found == path
    assert len(text.encode("utf-8")) == REPORT_MAX_BYTES
