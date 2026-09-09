"""Config surface tests (Clean 30/30, ADR 0006): generated docs stay in sync.

Units under test: core.config (field metadata, settings table, toml header),
core.limits (tunables table), cli.config (CONFIG.md region splicer, the
`fleet config docs` command).
"""

from __future__ import annotations

import re
from dataclasses import fields
from pathlib import Path

from typer.testing import CliRunner

from fleet.cli import config as config_cli
from fleet.cli.main import app
from fleet.core import config as config_mod
from fleet.core import limits as limits_mod
from fleet.core.config import RuntimeConfig

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src" / "fleet"

_ENV_READER = r"""(?:os\.environ|os\.getenv|environ)\s*(?:\[\s*|\.\s*get\s*\(\s*)"""
_ENV_CALL = re.compile(_ENV_READER + r"""["']([A-Z][A-Z0-9_]{2,})["']""")
_ENV_CONST_DEF = re.compile(r"""^([A-Z][A-Z0-9_]*_ENV)\s*=\s*["']([A-Z][A-Z0-9_]{2,})["']""", re.M)
_ENV_CONST_USE = re.compile(_ENV_READER + r"""([A-Z][A-Z0-9_]*_ENV)""")


def _env_reads() -> set[str]:
    """Every env-var name read via os.environ/os.getenv/environ in src/fleet."""
    names: set[str] = set()
    consts: dict[str, str] = {}
    uses: set[str] = set()
    for path in sorted(SRC.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        names.update(_ENV_CALL.findall(text))
        for const, value in _ENV_CONST_DEF.findall(text):
            consts[const] = value
        uses.update(_ENV_CONST_USE.findall(text))
    for const in uses:
        assert const in consts, f"{const} has no literal value in src/fleet"
        names.add(consts[const])
    return names


def test_every_field_has_doc_and_example() -> None:
    """Each RuntimeConfig field carries doc + example metadata."""
    missing = [
        f.name
        for f in fields(RuntimeConfig)
        if not f.metadata.get("doc") or not f.metadata.get("example")
    ]
    assert not missing, f"fields without doc/example metadata: {missing}"


def test_settings_table_covers_every_field() -> None:
    """Settings table has one row per field, no extras, with real defaults."""
    table = config_mod.render_settings_table()
    config = RuntimeConfig()
    for f in fields(config):
        assert f"`{f.name}`" in table, f"field {f.name} missing from settings table"
    rows = [line for line in table.splitlines() if line.startswith("| `")]
    assert len(rows) == len(fields(config)), "settings table has extra rows"


def test_settings_table_example_is_a_valid_value() -> None:
    """Every example in the table coerces for its field (docs never lie)."""
    for row in config_mod.setting_rows():
        config_mod.coerce(row.name, row.example)


def test_toml_header_matches_generator() -> None:
    """runtime.toml.header on disk equals the generator output."""
    header_path = SRC / "templates" / "runtime.toml.header"
    assert header_path.read_text(encoding="utf-8") == config_mod.render_toml_header()


def test_config_doc_regions_match_generator() -> None:
    """docs/CONFIG.md on disk equals the spliced generator output."""
    for path_str, expected in config_cli.expected_doc_files().items():
        assert Path(path_str).read_text(encoding="utf-8") == expected, path_str


def test_every_limit_constant_has_tunable_doc() -> None:
    """Every public UPPER_SNAKE constant in limits.py is in TUNABLE_DOCS."""
    constants = {
        name
        for name, value in vars(limits_mod).items()
        if name.isupper() and not name.startswith("_") and not callable(value)
    } - {"TUNABLE_DOCS"}
    assert constants == set(limits_mod.TUNABLE_DOCS), (
        f"missing docs: {sorted(constants - set(limits_mod.TUNABLE_DOCS))}; "
        f"stale docs: {sorted(set(limits_mod.TUNABLE_DOCS) - constants)}"
    )


def test_tunables_table_covers_every_constant() -> None:
    """Tunables table names every constant with its live value."""
    table = limits_mod.render_tunables_table()
    for row in limits_mod.tunable_rows():
        assert f"`{row.name}`" in table
        assert f"`{row.value}`" in table


def test_every_env_read_is_documented() -> None:
    """Each env var read in src/fleet appears in docs/CONFIG.md."""
    doc = (REPO_ROOT / "docs" / "CONFIG.md").read_text(encoding="utf-8")
    missing = [name for name in sorted(_env_reads()) if name not in doc]
    assert not missing, f"env vars missing from docs/CONFIG.md: {missing}"


def test_docs_command_prints_settings_table() -> None:
    """`fleet config docs` renders the same table as the library helper."""
    result = CliRunner().invoke(app, ["config", "docs"])
    assert result.exit_code == 0, result.output
    assert result.output == config_mod.render_settings_table()


def test_docs_check_passes_in_sync_tree() -> None:
    """`fleet config docs --check` exits 0 when generated files are current."""
    result = CliRunner().invoke(app, ["config", "docs", "--check"])
    assert result.exit_code == 0, result.output
