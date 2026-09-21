"""Locate and read the INVESTIGATION.md an investigator bead wrote.

The bundled blocked-task investigator writes its report into its OWN task
directory. `artifacts/` is what the shipped trigger text asks for; `outputs/`
(the ADR 0004 deliverables directory) is accepted too so a worker that follows
the fleet convention is still found. Reads are capped and never raise.
"""

from __future__ import annotations

from pathlib import Path

from fleet.state.paths import OUTPUTS_DIR

INVESTIGATION_MD = "INVESTIGATION.md"
ARTIFACTS_DIR = "artifacts"
REPORT_MAX_BYTES = 16384


def report_path(task_dir: Path) -> Path | None:
    """First existing INVESTIGATION.md under artifacts/ then outputs/, else None."""
    for parent in (task_dir / ARTIFACTS_DIR, task_dir / OUTPUTS_DIR):
        candidate = parent / INVESTIGATION_MD
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
