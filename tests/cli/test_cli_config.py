"""Tests for `fleet config show` and `fleet config set` (FR-24)."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from fleet.cli import app

runner = CliRunner()


def _patch_root(tmp_path: Path):
    return patch("fleet.cli._fleet_home", return_value=tmp_path)


# ---------------------------------------------------------------------------
# fleet config show
# ---------------------------------------------------------------------------


def test_config_show_prints_expected_keys(tmp_path: Path) -> None:
    with _patch_root(tmp_path):
        result = runner.invoke(app, ["config", "show"])
    assert result.exit_code == 0
    for key in (
        "max_concurrent",
        "retry_limit",
        "config_poll_interval_sec",
        "claim_poll_interval_sec",
    ):
        assert key in result.output, f"Expected '{key}' in config show output"


def test_config_show_displays_default_values(tmp_path: Path) -> None:
    with _patch_root(tmp_path):
        result = runner.invoke(app, ["config", "show"])
    assert result.exit_code == 0
    assert "3" in result.output   # default max_concurrent


def test_config_show_raw_cats_toml(tmp_path: Path) -> None:
    config_path = tmp_path / "runtime.toml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text("max_concurrent = 7\n", encoding="utf-8")
    with _patch_root(tmp_path):
        result = runner.invoke(app, ["config", "show", "--raw"])
    assert result.exit_code == 0
    assert "max_concurrent = 7" in result.output


def test_config_show_raw_no_file_prints_comment(tmp_path: Path) -> None:
    with _patch_root(tmp_path):
        result = runner.invoke(app, ["config", "show", "--raw"])
    assert result.exit_code == 0
    assert "No config file found" in result.output


# ---------------------------------------------------------------------------
# fleet config set
# ---------------------------------------------------------------------------


def test_config_set_updates_file(tmp_path: Path) -> None:
    with _patch_root(tmp_path):
        result = runner.invoke(app, ["config", "set", "max_concurrent=2"])
    assert result.exit_code == 0
    toml_path = tmp_path / "runtime.toml"
    assert toml_path.exists()
    content = toml_path.read_text(encoding="utf-8")
    assert "max_concurrent = 2" in content


def test_config_set_echoes_resulting_config(tmp_path: Path) -> None:
    with _patch_root(tmp_path):
        result = runner.invoke(app, ["config", "set", "max_concurrent=5"])
    assert result.exit_code == 0
    assert "max_concurrent" in result.output
    assert "5" in result.output


def test_config_set_atomicity_bad_value_leaves_file_unchanged(tmp_path: Path) -> None:
    """max_concurrent=2 retry_limit=garbage must leave the file at max_concurrent=4."""
    config_path = tmp_path / "runtime.toml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text("max_concurrent = 4\n", encoding="utf-8")

    with _patch_root(tmp_path):
        result = runner.invoke(app, ["config", "set", "max_concurrent=2", "claim_poll_interval_sec=garbage"])

    assert result.exit_code != 0
    content = config_path.read_text(encoding="utf-8")
    # File must be unchanged — max_concurrent stays 4, not 2
    assert "max_concurrent = 4" in content
    assert "max_concurrent = 2" not in content


def test_config_set_unknown_key_exits_nonzero(tmp_path: Path) -> None:
    with _patch_root(tmp_path):
        result = runner.invoke(app, ["config", "set", "unknown_key=1"])
    assert result.exit_code != 0


def test_config_set_unknown_key_message_contains_unknown(tmp_path: Path) -> None:
    with _patch_root(tmp_path):
        result = runner.invoke(app, ["config", "set", "unknown_key=1"])
    assert "unknown" in result.output.lower()


def test_config_set_multiple_keys(tmp_path: Path) -> None:
    with _patch_root(tmp_path):
        result = runner.invoke(app, ["config", "set", "max_concurrent=4", "claim_poll_interval_sec=5"])
    assert result.exit_code == 0
    toml_path = tmp_path / "runtime.toml"
    content = toml_path.read_text(encoding="utf-8")
    assert "max_concurrent = 4" in content
    assert "claim_poll_interval_sec = 5" in content
