"""Run directory layout (docs/27_sep_upgrade/DESIGN.md §3.4).

One folder per run under ``$FLEET_HOME/runs``: a frozen copy of the flow
file plus one directory per step run, laid out like the worker contract
task directory (``STATE.md``, ``attempts/``, ``outputs/outputs.json``).
"""

from __future__ import annotations

import json
import logging
import secrets
import shutil
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

NO_ITEM = -1

_BASE32_LOWER = "abcdefghijklmnopqrstuvwxyz234567"


def runs_root(fleet_home: Path) -> Path:
    """The directory holding every run (``fleet_home / "runs"``)."""
    return fleet_home / "runs"


def run_dir(fleet_home: Path, run_id: str) -> Path:
    """The directory for one run (``runs_root / run_id``)."""
    return runs_root(fleet_home) / run_id


def flow_copy(run_dir: Path) -> Path:
    """The run's frozen flow definition (``run_dir / "flow.yaml"``)."""
    return run_dir / "flow.yaml"


def inputs_file(run_dir: Path) -> Path:
    """The run's recorded inputs (``run_dir / "inputs.json"``)."""
    return run_dir / "inputs.json"


def step_dir(run_dir: Path, step: str, item_index: int = NO_ITEM) -> Path:
    """The directory for one step run.

    Plain steps live at ``run_dir / step``; ``for_each`` items live at
    ``run_dir / step / "items" / str(item_index)``.
    """
    if item_index == NO_ITEM:
        return run_dir / step
    return run_dir / step / "items" / str(item_index)


def outputs_file(step_dir: Path) -> Path:
    """The step run's outputs file (``step_dir / "outputs" / "outputs.json"``)."""
    return step_dir / "outputs" / "outputs.json"


def attempts_root(step_dir: Path) -> Path:
    """The attempts directory holding one folder per attempt (``step_dir / "attempts"``)."""
    return step_dir / "attempts"


def attempt_dir(step_dir: Path, attempt_n: int) -> Path:
    """The per-attempt directory (``attempts_root / str(attempt_n)``)."""
    return attempts_root(step_dir) / str(attempt_n)


def checks_dir(attempt_dir: Path) -> Path:
    """The check verdicts directory of one attempt (``attempt_dir / "checks"``)."""
    return attempt_dir / "checks"


def check_file(attempt_dir: Path, name: str) -> Path:
    """The verdict file of one check (``checks_dir / "<name>.json"``)."""
    return checks_dir(attempt_dir) / f"{name}.json"


def latest_attempt_dir(step_dir: Path) -> Path | None:
    """The highest-numbered attempt folder, or None when there is none."""
    root = attempts_root(step_dir)
    if not root.is_dir():
        return None
    numbered = [child for child in root.iterdir() if child.is_dir() and child.name.isdigit()]
    if not numbered:
        return None
    return max(numbered, key=lambda child: int(child.name))


def read_verdicts(step_dir: Path) -> dict[str, dict[str, Any]]:
    """Verdicts of the latest attempt: {name: {"ok", "message", "outputs", ...}}.

    Reads every ``checks/*.json`` of the latest attempt; unreadable or
    non-object files are skipped. A verdict file holds at least
    ``{"name", "ok", "message"}``; ``outputs`` (any JSON) and
    ``duration_s`` are optional.
    """
    latest = latest_attempt_dir(step_dir)
    if latest is None:
        return {}
    verdicts: dict[str, dict[str, Any]] = {}
    folder = checks_dir(latest)
    if not folder.is_dir():
        return {}
    for path in sorted(folder.glob("*.json")):
        try:
            decoded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            logger.warning("verdict_invalid: %s", path)
            continue
        if not isinstance(decoded, dict):
            logger.warning("verdict_invalid: %s (not a JSON object)", path)
            continue
        name = decoded.get("name")
        key = name if isinstance(name, str) and name else path.stem
        verdicts[key] = dict(decoded)
    return verdicts


def read_outputs(step_dir: Path) -> dict[str, Any]:
    """Step outputs published by a step run (`outputs/outputs.json`).

    A missing file means the step published nothing: return {}. An
    invalid file (unparseable JSON or a non-object) is ignored with an
    `outputs_invalid` warning. JSON types are preserved (a list stays a
    list).
    """
    path = outputs_file(step_dir)
    if not path.is_file():
        return {}
    try:
        decoded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("outputs_invalid: %s (%s)", path, exc)
        return {}
    if not isinstance(decoded, dict):
        logger.warning("outputs_invalid: %s (not a JSON object)", path)
        return {}
    return dict(decoded)


def new_run_id(now: datetime) -> str:
    """A new run id: ``run-<yyyymmdd>-<6 random lowercase base32 chars>``."""
    suffix = "".join(secrets.choice(_BASE32_LOWER) for _ in range(6))
    return f"run-{now.strftime('%Y%m%d')}-{suffix}"


def create_run_dir(
    fleet_home: Path, run_id: str, flow_source: Path, inputs: Mapping[str, Any]
) -> Path:
    """Create a run directory with its frozen flow copy and inputs file.

    Raises FileExistsError if the run directory already exists.
    """
    target = run_dir(fleet_home, run_id)
    if target.exists():
        raise FileExistsError(target)
    target.mkdir(parents=True)
    shutil.copyfile(flow_source, flow_copy(target))
    inputs_file(target).write_text(
        json.dumps(dict(inputs), indent=2, sort_keys=True), encoding="utf-8"
    )
    return target


def create_step_dir(run_dir: Path, step: str, item_index: int = NO_ITEM) -> Path:
    """Create a step run directory (plus its ``outputs/``) without clobbering.

    Existing directories and files are left alone; returns the step dir.
    """
    target = step_dir(run_dir, step, item_index)
    target.mkdir(parents=True, exist_ok=True)
    (target / "outputs").mkdir(parents=True, exist_ok=True)
    return target
