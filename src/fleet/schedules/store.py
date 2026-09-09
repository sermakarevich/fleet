"""On-disk store for schedules and their run history (the only file-layout owner).

Definitions live in `$FLEET_HOME/schedules/<id>.json`; run history is an
append-only `$FLEET_HOME/schedules/<id>.runs.jsonl` (one JSON object per
line). Called by the serve API and the CLI (definitions) and by whoever
fires a run (run history). Schedule ids are validated before touching paths.
"""

from __future__ import annotations

import builtins
import json
import re
from pathlib import Path

import structlog

from fleet.schedules.model import Schedule, ScheduleRun, Trigger
from fleet.state.atomic import write_json_atomic

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,39}$")


class ScheduleStore:
    """Reads and writes schedule definitions and run history under fleet home."""

    def __init__(self, fleet_home: Path) -> None:
        """Point the store at `$FLEET_HOME/schedules` (created on first write)."""
        self.root = Path(fleet_home) / "schedules"
        self._log = structlog.get_logger()

    def _path(self, schedule_id: str) -> Path:
        """Definition file for an id, after validating the id."""
        self._check_id(schedule_id)
        return self.root / f"{schedule_id}.json"

    def _runs_path(self, schedule_id: str) -> Path:
        """Run-history file for an id, after validating the id."""
        self._check_id(schedule_id)
        return self.root / f"{schedule_id}.runs.jsonl"

    @staticmethod
    def _check_id(schedule_id: str) -> None:
        """Raise ValueError when an id could escape the schedules directory."""
        if not _ID_RE.match(schedule_id):
            raise ValueError(f"schedule id: invalid {schedule_id!r}")

    def _read_schedule(self, path: Path) -> Schedule | None:
        """Parse one definition file, or None (logged) when unreadable."""
        try:
            return Schedule.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError) as exc:
            self._log.warning("schedule unreadable", path=str(path), error=str(exc))
            return None

    def list(self) -> builtins.list[Schedule]:
        """All readable schedules, sorted by name then id."""
        if not self.root.is_dir():
            return []
        found = [
            schedule
            for path in sorted(self.root.glob("*.json"))
            if path.suffix == ".json"
            and not path.name.endswith(".runs.jsonl")
            and (schedule := self._read_schedule(path)) is not None
        ]
        return sorted(found, key=lambda item: (item.name, item.id))

    def get(self, schedule_id: str) -> Schedule | None:
        """One schedule by id, or None when missing or unreadable."""
        path = self._path(schedule_id)
        if not path.is_file():
            return None
        return self._read_schedule(path)

    def save(self, schedule: Schedule) -> None:
        """Write a schedule definition atomically (creates the directory)."""
        write_json_atomic(self._path(schedule.id), schedule.to_dict())

    def delete(self, schedule_id: str) -> bool:
        """Remove a schedule and its run history; False when nothing existed."""
        removed = False
        for path in (self._path(schedule_id), self._runs_path(schedule_id)):
            existed = path.exists()
            try:
                path.unlink(missing_ok=True)
            except OSError as exc:
                self._log.warning("schedule delete failed", path=str(path), error=str(exc))
            else:
                removed = existed or removed
        return removed

    def runs(self, schedule_id: str, limit: int = 100) -> builtins.list[ScheduleRun]:
        """Run history, newest first (malformed lines are skipped and logged)."""
        path = self._runs_path(schedule_id)
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        parsed: builtins.list[ScheduleRun] = []
        for line in lines:
            if not line.strip():
                continue
            try:
                parsed.append(ScheduleRun.from_dict(json.loads(line)))
            except (ValueError, TypeError, AttributeError) as exc:
                self._log.warning("run line unreadable", path=str(path), error=str(exc))
        parsed.sort(key=lambda run: run.n, reverse=True)
        return parsed[: max(0, limit)]

    def last_run(self, schedule_id: str, trigger: Trigger | None = None) -> ScheduleRun | None:
        """Newest run, optionally only of one trigger kind, or None."""
        for run in self.runs(schedule_id, limit=10_000):
            if trigger is None or run.trigger == trigger:
                return run
        return None

    def append_run(self, run: ScheduleRun) -> None:
        """Append one run line to the history (creates the directory)."""
        path = self._runs_path(run.schedule_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(run.to_dict()) + "\n")
            handle.flush()

    def run_count(self, schedule_id: str) -> int:
        """Number of non-blank run lines stored for a schedule."""
        path = self._runs_path(schedule_id)
        try:
            return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
        except OSError:
            return 0
