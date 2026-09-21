"""On-disk store for triggers and their firing history (the only file-layout owner).

Definitions live in `$FLEET_HOME/triggers/<id>.json`; firing history is an
append-only `$FLEET_HOME/triggers/<id>.firings.jsonl` (one JSON object per
line). Called by the serve API and the CLI (definitions) and by whoever
fires a trigger (firing history). Trigger ids are validated before touching
paths.
"""

from __future__ import annotations

import builtins
import json
import os
import re
from pathlib import Path

import structlog

from fleet.state import paths as state_paths
from fleet.state.atomic import write_text_atomic
from fleet.triggers.model import Firing, Trigger

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,39}$")


class TriggerStore:
    """Reads and writes trigger definitions and firing history under fleet home."""

    def __init__(self, fleet_home: Path) -> None:
        """Point the store at the triggers root (created on first write)."""
        self.root = state_paths.triggers_root(Path(fleet_home))
        self._log = structlog.get_logger()

    def _path(self, trigger_id: str) -> Path:
        """Definition file for an id, after validating the id."""
        self._check_id(trigger_id)
        return self.root / f"{trigger_id}.json"

    def _firings_path(self, trigger_id: str) -> Path:
        """Firing-history file for an id, after validating the id."""
        self._check_id(trigger_id)
        return self.root / f"{trigger_id}.firings.jsonl"

    @staticmethod
    def _check_id(trigger_id: str) -> None:
        """Raise ValueError when an id could escape the triggers directory."""
        if not _ID_RE.match(trigger_id):
            raise ValueError(f"trigger id: invalid {trigger_id!r}")

    def _read_trigger(self, path: Path) -> Trigger | None:
        """Parse one definition file, or None (logged) when unreadable."""
        try:
            return Trigger.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError) as exc:
            self._log.warning("trigger unreadable", path=str(path), error=str(exc))
            return None

    def list(self) -> builtins.list[Trigger]:
        """All readable triggers, sorted by id."""
        if not self.root.is_dir():
            return []
        found = [
            trigger
            for path in sorted(self.root.glob("*.json"))
            if path.suffix == ".json"
            and not path.name.endswith(".firings.jsonl")
            and (trigger := self._read_trigger(path)) is not None
        ]
        return sorted(found, key=lambda item: item.id)

    def get(self, trigger_id: str) -> Trigger | None:
        """One trigger by id, or None when missing or unreadable."""
        path = self._path(trigger_id)
        if not path.is_file():
            return None
        return self._read_trigger(path)

    def save(self, trigger: Trigger) -> None:
        """Write a trigger definition atomically (creates the directory)."""
        write_text_atomic(self._path(trigger.id), json.dumps(trigger.to_dict(), indent=2))

    def delete(self, trigger_id: str) -> bool:
        """Remove a trigger and its firing history; False when nothing existed."""
        removed = False
        for path in (self._path(trigger_id), self._firings_path(trigger_id)):
            existed = path.exists()
            try:
                path.unlink(missing_ok=True)
            except OSError as exc:
                self._log.warning("trigger delete failed", path=str(path), error=str(exc))
            else:
                removed = existed or removed
        return removed

    def firings(self, trigger_id: str, limit: int = 100) -> builtins.list[Firing]:
        """Firing history, newest first (malformed lines are skipped and logged)."""
        self._check_id(trigger_id)
        path = self._firings_path(trigger_id)
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        parsed: builtins.list[Firing] = []
        for line in lines:
            if not line.strip():
                continue
            try:
                parsed.append(Firing.from_dict(json.loads(line)))
            except (ValueError, TypeError, AttributeError) as exc:
                self._log.warning("firing line unreadable", path=str(path), error=str(exc))
        parsed.sort(key=lambda firing: firing.n, reverse=True)
        return parsed[: max(0, limit)]

    def append_firing(self, firing: Firing) -> None:
        """Append one firing line to the history (creates the directory)."""
        path = self._firings_path(firing.trigger_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(firing.to_dict()) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def firing_count(self, trigger_id: str) -> int:
        """Number of non-blank firing lines stored for a trigger."""
        self._check_id(trigger_id)
        path = self._firings_path(trigger_id)
        try:
            return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
        except OSError:
            return 0

    def has_fired(self, trigger_id: str, event_key: str) -> bool:
        """True when a non-skipped firing with this event key exists."""
        return any(
            firing.event_key == event_key and not firing.skipped
            for firing in self.firings(trigger_id, limit=10_000)
        )

    def firing_for_event(self, trigger_id: str, event_key: str) -> Firing | None:
        """Newest non-skipped firing of this trigger for `event_key`, or None."""
        for firing in self.firings(trigger_id, limit=10_000):
            if firing.event_key == event_key and not firing.skipped:
                return firing
        return None

    def last_firing(self, trigger_id: str) -> Firing | None:
        """Newest non-skipped firing, or None when there is none."""
        for firing in self.firings(trigger_id, limit=10_000):
            if not firing.skipped:
                return firing
        return None
