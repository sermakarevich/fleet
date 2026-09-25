"""Locate and read the HELPER_REPORT.md a helper bead wrote.

The blocked-task helper writes its report into its OWN task directory.
`artifacts/` is what the shipped prompt template asks for; `outputs/`
(the ADR 0004 deliverables directory) is accepted too so a worker that
follows the fleet convention is still found. Reads are capped and never
raise.
"""

from __future__ import annotations

from pathlib import Path

from fleet.state.paths import OUTPUTS_DIR

HELPER_REPORT_MD = "HELPER_REPORT.md"
ARTIFACTS_DIR = "artifacts"
REPORT_MAX_BYTES = 16384


def report_path(task_dir: Path) -> Path | None:
    """First existing HELPER_REPORT.md under artifacts/ then outputs/, else None."""
    for parent in (task_dir / ARTIFACTS_DIR, task_dir / OUTPUTS_DIR):
        candidate = parent / HELPER_REPORT_MD
        if candidate.is_file():
            return candidate
    return None


def read_report(task_dir: Path) -> tuple[str, Path] | None:
    """(text, path) of the report capped at REPORT_MAX_BYTES, or None."""
    path = report_path(task_dir)
    if path is None:
        return None
    try:
        data = path.read_bytes()
    except OSError:
        return None
    return data[:REPORT_MAX_BYTES].decode("utf-8", errors="ignore"), path
