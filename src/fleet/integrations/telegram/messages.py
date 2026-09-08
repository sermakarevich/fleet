"""Owner of the Telegram bookkeeping files under FLEET_HOME.

MessageStore maps a sent Telegram message_id back to its ask_human
question id so inbound replies route to the right question (used by
commands.py, written by notify.py). OffsetStore persists the getUpdates
offset so restarts never replay history (used by listener.py). Both
never raise on bad disks: reads fall back to empty, writes log and move
on, so a corrupt file can never stall the bot loop.
"""

from __future__ import annotations

import json
from pathlib import Path

import structlog

_log = structlog.get_logger(__name__)

_MESSAGE_CAP = 200  # sent-question mappings kept; oldest evicted past this


class MessageStore:
    """message_id -> question_id mapping backed by one JSON file."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def _read(self) -> dict:
        """Raw mapping; empty when the file is missing or corrupt."""
        try:
            mapping = json.loads(self.path.read_text(encoding="utf-8"))
            return mapping if isinstance(mapping, dict) else {}
        except (OSError, ValueError):
            return {}

    def record(self, message_id: int, question_id: str) -> None:
        """Persist message_id -> question_id, evicting oldest past the cap."""
        try:
            mapping = self._read()
            mapping[str(message_id)] = question_id
            if len(mapping) > _MESSAGE_CAP:
                for key in list(mapping)[: len(mapping) - _MESSAGE_CAP]:
                    del mapping[key]
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(mapping), encoding="utf-8")
        except OSError as exc:
            _log.warning("telegram.record_question_message failed", error=str(exc))

    def lookup(self, message_id: int) -> str | None:
        """Question id for *message_id*, or None when unknown."""
        value = self._read().get(str(message_id))
        return value if isinstance(value, str) else None


class OffsetStore:
    """getUpdates offset backed by one text file."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> int | None:
        """Persisted offset; None when absent or invalid (start from live)."""
        try:
            return int(self.path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return None

    def save(self, offset: int) -> None:
        """Persist *offset*; a bad disk never kills the loop."""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(str(offset), encoding="utf-8")
        except OSError as exc:
            _log.warning("telegram.save_offset failed", error=str(exc))
