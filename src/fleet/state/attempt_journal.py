"""The one owner of ``attempts.jsonl``.

:class:`AttemptJournal` reads the journal file ONCE (:meth:`load`) and
answers every derived question from the in-memory rows: ``rows``,
``starts``, ``max_n``, ``current_n``, ``restart_count`` and ``last``.
Writers (``append_start``, ``append_end``, ``append_unblock``,
``set_worker``) append or rewrite through the atomic writer. Nobody else
parses this file. Callers are ``state/attempts.py`` (thin shims),
``orchestrator/spawn.py``, ``orchestrator/reap.py``,
``orchestrator/leases.py`` and the workers.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog

from fleet.core.iso import now_iso, parse_iso
from fleet.core.retry_policy import Action
from fleet.core.task import AttemptKind
from fleet.state.atomic import write_text_atomic
from fleet.state.paths import ATTEMPTS_JSONL, attempt_dir

logger = structlog.get_logger(__name__)


def _journal_path(task_dir: Path) -> Path:
    """Path of the append-only journal file for *task_dir*."""
    return task_dir / ATTEMPTS_JSONL


def _read_lines(path: Path) -> list[dict[str, Any]]:
    """Raw JSON-object lines of the journal; skips blanks and garbage."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    rows: list[dict[str, Any]] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if isinstance(obj, dict):
            rows.append(obj)
    return rows


def _row_n(obj: dict[str, Any]) -> int | None:
    """Attempt number of a raw journal line, or None when not an int."""
    try:
        return int(obj.get("n"))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _merge_rows(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fold start/end/unblock lines by n into per-attempt dicts sorted by n."""
    by_n: dict[int, dict[str, Any]] = {}
    for obj in raw:
        event = obj.get("event")
        n = _row_n(obj)
        if n is None:
            continue
        entry = by_n.setdefault(n, {"n": n})
        if event == "start":
            entry["started_at"] = obj.get("ts")
            entry["coder"] = obj.get("coder")
            entry["model"] = obj.get("model")
            entry["worker"] = obj.get("worker")
            entry["kind"] = obj.get("kind", "work")
        elif event == "end":
            entry["ended_at"] = obj.get("ts")
            entry["outcome"] = obj.get("outcome")
            entry["exit_code"] = obj.get("exit_code")
            entry["reason"] = obj.get("reason")
            entry["action"] = obj.get("action")
        elif event == "unblock":
            entry["started_at"] = obj.get("ts")
            entry["ended_at"] = obj.get("ts")
            entry["kind"] = "unblock"
            entry["outcome"] = "unblocked"
            entry["reason"] = obj.get("reason")
            entry["action"] = "release"
    return [_finish_row(by_n[n]) for n in sorted(by_n)]


def _finish_row(entry: dict[str, Any]) -> dict[str, Any]:
    """Fill defaults and duration for one merged attempt row."""
    merged = {
        "n": entry["n"],
        "started_at": entry.get("started_at"),
        "ended_at": entry.get("ended_at"),
        "coder": entry.get("coder"),
        "model": entry.get("model"),
        "worker": entry.get("worker"),
        "kind": entry.get("kind", "work"),
        "outcome": entry.get("outcome"),
        "exit_code": entry.get("exit_code"),
        "reason": entry.get("reason"),
        "action": entry.get("action"),
        "duration_sec": None,
    }
    start = parse_iso(merged["started_at"])
    end = parse_iso(merged["ended_at"])
    if start is not None and end is not None:
        merged["duration_sec"] = (end - start).total_seconds()
    return merged


def _append_line(task_dir: Path, entry: dict[str, Any]) -> None:
    """Append one JSON line to the journal, creating the task dir."""
    task_dir.mkdir(parents=True, exist_ok=True)
    with _journal_path(task_dir).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry) + "\n")


@dataclass
class AttemptJournal:
    """One in-memory reading of attempts.jsonl plus its writers."""

    task_dir: Path
    raw: list[dict[str, Any]] = field(default_factory=list)
    rows: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def load(cls, task_dir: Path) -> AttemptJournal:
        """Read the journal file once; missing file means no attempts."""
        raw = _read_lines(_journal_path(task_dir))
        return cls(task_dir=task_dir, raw=raw, rows=_merge_rows(raw))

    @property
    def starts(self) -> int:
        """Number of start lines (work + compact attempts alike)."""
        return sum(1 for obj in self.raw if obj.get("event") == "start")

    @property
    def max_n(self) -> int:
        """Highest n in any start/end/unblock line, or 0 when empty."""
        best = 0
        for obj in self.raw:
            if obj.get("event") in ("start", "end", "unblock"):
                n = _row_n(obj)
                if n is not None:
                    best = max(best, n)
        return best

    @property
    def current_n(self) -> int:
        """Highest start n seen so far, or 0 when no attempt started."""
        best = 0
        for obj in self.raw:
            if obj.get("event") == "start":
                n = _row_n(obj)
                if n is not None:
                    best = max(best, n)
        return best

    @property
    def restart_count(self) -> int:
        """Number of starts minus 1, minimum 0."""
        return max(self.starts - 1, 0)

    @property
    def last(self) -> dict[str, Any] | None:
        """Last merged row, or None when the journal is empty."""
        return self.rows[-1] if self.rows else None

    def append_start(
        self,
        *,
        coder: str | None,
        model: str | None,
        worker: str | None = None,
        kind: AttemptKind | str = AttemptKind.WORK,
    ) -> int:
        """Journal a start line and return its attempt number."""
        n = self.max_n + 1
        kind_value = kind.value if isinstance(kind, AttemptKind) else kind
        entry = {
            "event": "start",
            "n": n,
            "ts": now_iso(),
            "coder": coder,
            "model": model,
            "worker": worker,
            "kind": kind_value,
        }
        _append_line(self.task_dir, entry)
        self.raw.append(dict(entry))
        self.rows = _merge_rows(self.raw)
        return n

    def append_end(
        self,
        *,
        outcome: str,
        exit_code: int | None,
        reason: str,
        action: Action | str,
        n: int | None = None,
    ) -> int:
        """Journal an end line for attempt *n* (default: the current one)."""
        if n is None:
            n = self.current_n or self.max_n + 1
        action_value = action.value if isinstance(action, Action) else action
        entry = {
            "event": "end",
            "n": n,
            "ts": now_iso(),
            "outcome": outcome,
            "exit_code": exit_code,
            "reason": reason,
            "action": action_value,
        }
        _append_line(self.task_dir, entry)
        self.raw.append(dict(entry))
        self.rows = _merge_rows(self.raw)
        return n

    def append_unblock(self, note: str | None = None) -> int:
        """Journal an operator-unblock row with its own attempt number."""
        n = self.max_n + 1
        entry = {
            "event": "unblock",
            "n": n,
            "ts": now_iso(),
            "reason": note or "unblocked by operator",
        }
        _append_line(self.task_dir, entry)
        self.raw.append(dict(entry))
        self.rows = _merge_rows(self.raw)
        return n

    def set_worker(self, n: int, worker: str) -> bool:
        """Tag attempt *n*'s start line with its worker name.

        Returns True when a line was tagged. A missing journal or a missing
        start line logs a warning and returns False; a failed rewrite logs
        and re-raises so callers never assume the tag landed.
        """
        path = _journal_path(self.task_dir)
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("attempt_journal_read_failed", task=str(self.task_dir), error=str(exc))
            return False
        changed = False
        out_lines: list[str] = []
        for raw_line in text.splitlines():
            stripped = raw_line.strip()
            try:
                obj = json.loads(stripped) if stripped else None
            except ValueError:
                obj = None
            if isinstance(obj, dict) and obj.get("event") == "start" and obj.get("n") == n:
                obj["worker"] = worker
                out_lines.append(json.dumps(obj))
                changed = True
            else:
                out_lines.append(raw_line)
        if not changed:
            logger.warning("attempt_journal_no_start", task=str(self.task_dir), n=n)
            return False
        try:
            write_text_atomic(path, "\n".join(out_lines) + "\n")
        except OSError:
            logger.exception("attempt_journal_rewrite_failed", task=str(self.task_dir), n=n)
            raise
        for obj in self.raw:
            if obj.get("event") == "start" and obj.get("n") == n:
                obj["worker"] = worker
        self.rows = _merge_rows(self.raw)
        return True

    def latest_attempt_dir(self, before_n: int | None = None) -> Path | None:
        """Dir of the most recent attempt, or below *before_n* when given."""
        rows = self.rows
        if before_n is not None:
            rows = [row for row in rows if row["n"] < before_n]
        if not rows:
            return None
        running = [row["n"] for row in rows if row.get("started_at") and not row.get("ended_at")]
        if running:
            return attempt_dir(self.task_dir, max(running))
        return attempt_dir(self.task_dir, max(row["n"] for row in rows))
