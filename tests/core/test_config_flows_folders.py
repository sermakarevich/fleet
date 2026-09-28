"""flows_folders config field: defaults, coercion, expansion, restart, docs."""

from __future__ import annotations

from pathlib import Path

from fleet.core.config import (
    RESTART_REQUIRED_FIELDS,
    RuntimeConfig,
    expand_folders,
    merge,
    parse,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_default_is_builtin() -> None:
    assert RuntimeConfig().flows_folders == ["builtin"]


def test_comma_separated_string_coerces_to_list() -> None:
    merged = merge({}, {"flows_folders": "builtin,/tmp/x"})
    assert merged["flows_folders"] == ["builtin", "/tmp/x"]
    assert parse({"flows_folders": "builtin,/tmp/x"}).flows_folders == ["builtin", "/tmp/x"]


def test_toml_array_round_trips() -> None:
    config = parse({"flows_folders": ["builtin", "/tmp/x"]})
    assert config.flows_folders == ["builtin", "/tmp/x"]


def test_expand_folders_expands_tilde() -> None:
    expanded = expand_folders(["builtin", "~/.fleet/private"])
    assert expanded[0] == "builtin"
    assert expanded[1] == str(Path("~/.fleet/private").expanduser())
    assert "~" not in expanded[1]


def test_flows_folders_requires_restart() -> None:
    assert "flows_folders" in RESTART_REQUIRED_FIELDS


def test_docs_table_row_exists() -> None:
    doc = (REPO_ROOT / "docs" / "CONFIG.md").read_text(encoding="utf-8")
    assert "`flows_folders`" in doc
