"""Grep-based tests asserting documentation contracts (task-10)."""
from __future__ import annotations

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
FLEET_ROOT = PROJECT_ROOT / "src" / "fleet"
INSTRUCTION_MD = FLEET_ROOT / "templates" / "INSTRUCTION.md"
FLEET_README = PROJECT_ROOT / "README.md"


# ---------------------------------------------------------------------------
# FR-38: no `fleet block` / `fleet answer` in agent-facing docs
# ---------------------------------------------------------------------------


def _lines_matching(path: Path, pattern: str) -> list[str]:
    return [ln for ln in path.read_text().splitlines() if re.search(pattern, ln)]


def _lines_matching_as_command(path: Path, pattern: str) -> list[str]:
    """Return lines where pattern appears as a usage example (not in a negation/footnote)."""
    results = []
    for ln in path.read_text().splitlines():
        if re.search(pattern, ln, re.IGNORECASE):
            # Allow lines that are explicit "not provided" / "deferred" footnotes
            if re.search(r"\bnot\s+provide|\bdoes\s+not|\bdeferred\b|\bno\s+fleet\b", ln, re.IGNORECASE):
                continue
            results.append(ln)
    return results


def test_no_fleet_block_in_instruction_md():
    matches = _lines_matching_as_command(INSTRUCTION_MD, r"fleet\s+block")
    assert not matches, f"fleet/templates/INSTRUCTION.md contains 'fleet block' as a usage example: {matches}"


def test_no_fleet_answer_in_instruction_md():
    matches = _lines_matching_as_command(INSTRUCTION_MD, r"fleet\s+answer")
    assert not matches, f"fleet/templates/INSTRUCTION.md contains 'fleet answer' as a usage example: {matches}"


def test_no_fleet_block_in_fleet_readme():
    matches = _lines_matching_as_command(FLEET_README, r"fleet\s+block")
    assert not matches, f"fleet/README.md contains 'fleet block' as a usage example: {matches}"


def test_no_fleet_answer_in_fleet_readme():
    matches = _lines_matching_as_command(FLEET_README, r"fleet\s+answer")
    assert not matches, f"fleet/README.md contains 'fleet answer' as a usage example: {matches}"


# ---------------------------------------------------------------------------
# FR-15: `--resume` in INSTRUCTION.md only appears as "does NOT pass --resume"
# ---------------------------------------------------------------------------


def test_resume_flag_only_as_negation_in_instruction_md():
    content = INSTRUCTION_MD.read_text()
    for ln in content.splitlines():
        if "--resume" in ln:
            assert re.search(r"\bnot\b|\bNOT\b|\bnever\b|\bNEVER\b|\bdoes not\b|\bdoes NOT\b", ln, re.IGNORECASE), (
                f"INSTRUCTION.md line contains '--resume' without negation context: {ln!r}"
            )


# ---------------------------------------------------------------------------
# FR-16: Q&A protocol section mentions required bd commands
# ---------------------------------------------------------------------------


def test_instruction_md_mentions_bd_update():
    assert "bd update" in INSTRUCTION_MD.read_text(), "INSTRUCTION.md must mention 'bd update'"


def test_instruction_md_mentions_status_blocked():
    assert "--status blocked" in INSTRUCTION_MD.read_text(), "INSTRUCTION.md must mention '--status blocked'"


def test_instruction_md_mentions_status_open():
    assert "--status open" in INSTRUCTION_MD.read_text(), "INSTRUCTION.md must mention '--status open'"


def test_instruction_md_mentions_ask_human():
    assert "ask_human" in INSTRUCTION_MD.read_text(), "INSTRUCTION.md must mention 'ask_human'"


# ---------------------------------------------------------------------------
# File existence checks
# ---------------------------------------------------------------------------


def test_instruction_md_exists():
    assert INSTRUCTION_MD.exists(), f"fleet/templates/INSTRUCTION.md does not exist at {INSTRUCTION_MD}"


def test_fleet_readme_exists():
    assert FLEET_README.exists(), f"fleet/README.md does not exist at {FLEET_README}"


# ---------------------------------------------------------------------------
# FR-15: "read these files first" is the first content section in INSTRUCTION.md
# ---------------------------------------------------------------------------


def test_read_files_first_is_first_section():
    content = INSTRUCTION_MD.read_text()
    sections = [ln for ln in content.splitlines() if ln.startswith("## ")]
    assert sections, "INSTRUCTION.md has no ## sections"
    first = sections[0].lower()
    assert "read" in first and ("first" in first or "fresh" in first or "start" in first), (
        f"First ## section in INSTRUCTION.md should be the 'read files first' instruction, got: {sections[0]!r}"
    )
