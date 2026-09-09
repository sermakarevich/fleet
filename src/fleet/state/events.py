"""The one events.jsonl reader, plus the derived stats every caller needs.

``iter_events`` is the single tolerant line-by-line reader. ``scan_rows``
feeds every row through one small visitor per concern (see ``VISITORS``)
and assembles their fragments into an ``EventStats``. ``scan`` runs that
over all attempts; ``scan_cached`` reuses an ``EventScanCache`` owned and
passed in by the caller, so this module holds no shared state.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from fleet.core.iso import parse_iso as _parse_iso_clock
from fleet.core.task import EventKind, TaskOutcome

_TOUCH_TOOLS = {"Read": "read", "Edit": "edit", "Write": "write", "NotebookEdit": "edit"}


def parse_iso(ts: str) -> datetime | None:
    """Parse one event timestamp; None when missing or malformed."""
    return _parse_iso_clock(ts)


def safe_int(v: object) -> int:
    if isinstance(v, bool):
        return 0
    if isinstance(v, int):
        return v
    if isinstance(v, str):
        try:
            return int(v)
        except ValueError:
            return 0
    return 0


def _attempt_dirs_sorted(task_dir: Path) -> list[Path]:
    """List task_dir/attempts/<n> directories sorted numerically by n.

    Self-contained (no import of state.attempts) to avoid a state/-internal
    import cycle: attempts.py and events.py would otherwise both need each
    other's helpers.
    """
    attempts_root = task_dir / "attempts"
    if not attempts_root.is_dir():
        return []
    numbered: list[tuple[int, Path]] = []
    for child in attempts_root.iterdir():
        if not child.is_dir():
            continue
        try:
            n = int(child.name)
        except ValueError:
            continue
        numbered.append((n, child))
    numbered.sort(key=lambda pair: pair[0])
    return [p for _, p in numbered]


def _iter_events_file(events_file: Path) -> Iterator[dict]:
    """Yield each parsed JSON object from one events.jsonl file."""
    if not events_file.exists():
        return
    try:
        with events_file.open("r", encoding="utf-8") as fh:
            for raw_line in fh:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(row, dict):
                    yield row
    except OSError:
        return


def iter_events(task_dir: Path) -> Iterator[dict]:
    """Yield every event across all attempts, oldest attempt first.

    Reads task_dir/attempts/<n>/events.jsonl for every attempt directory,
    sorted numerically by *n* (so attempt 10 sorts after attempt 9, not
    lexicographically before it). Blank and malformed lines are skipped
    silently, same as before this became attempt-scoped.
    """
    for attempt_path in _attempt_dirs_sorted(task_dir):
        yield from _iter_events_file(attempt_path / "events.jsonl")


def iter_attempt_events(task_dir: Path, n: int) -> Iterator[dict]:
    """Yield the parsed events for one attempt's events.jsonl only."""
    yield from _iter_events_file(task_dir / "attempts" / str(n) / "events.jsonl")


@dataclass(frozen=True, slots=True)
class FileCounts:
    read: int = 0
    edit: int = 0
    write: int = 0


@dataclass(frozen=True, slots=True)
class EventStats:
    event_count: int = 0
    first_ts: datetime | None = None
    last_ts: datetime | None = None
    last_kind: str | None = None
    last_detail: str | None = None
    peak_context_tokens: int | None = None
    current_context_tokens: int | None = None
    steps: int = 0
    segments: int = 0
    errors: int = 0
    tool_counts: dict[str, int] = field(default_factory=dict)
    output_tokens: int = 0
    input_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    files_touched: dict[str, FileCounts] = field(default_factory=dict)
    hour_hist: dict[str, int] = field(default_factory=dict)
    context_pressure: bool = False
    rate_limited: int = 0
    rate_limit_events: list[dict] = field(default_factory=list)

    @property
    def files_touched_count(self) -> int:
        return len(self.files_touched)


class EventVisitor(ABC):
    """One per-row accumulator behind scan_rows; subclass per concern."""

    @abstractmethod
    def visit(self, row: dict) -> None:
        """Fold one event row into this visitor's running state."""

    @abstractmethod
    def result(self) -> Any:
        """Return this visitor's fragment of the final EventStats."""


@dataclass(frozen=True)
class TimingResult:
    first_ts: datetime | None
    last_ts: datetime | None
    hour_hist: dict[str, int]


class CountVisitor(EventVisitor):
    """Counts every row, with or without a timestamp."""

    def __init__(self) -> None:
        self._count = 0

    def visit(self, row: dict) -> None:
        """Count one row."""
        self._count += 1

    def result(self) -> int:
        """Return the row count."""
        return self._count


class TimingVisitor(EventVisitor):
    """Tracks first/last timestamps plus a weekday-hour histogram."""

    def __init__(self) -> None:
        self._first: datetime | None = None
        self._last: datetime | None = None
        self._hour_hist: dict[str, int] = {}

    def visit(self, row: dict) -> None:
        """Fold one row's timestamp into the range and histogram."""
        ts_str = row.get("ts")
        if not isinstance(ts_str, str):
            return
        ts_dt = parse_iso(ts_str)
        if ts_dt is None:
            return
        if self._first is None or ts_dt < self._first:
            self._first = ts_dt
        if self._last is None or ts_dt > self._last:
            self._last = ts_dt
        key = f"{ts_dt.weekday()}-{ts_dt.hour}"
        self._hour_hist[key] = self._hour_hist.get(key, 0) + 1

    def result(self) -> TimingResult:
        """Return the time range and histogram."""
        return TimingResult(self._first, self._last, self._hour_hist)


@dataclass(frozen=True)
class LastEvent:
    kind: str | None
    detail: str | None


class LastEventVisitor(EventVisitor):
    """Remembers the last row's kind and tool name."""

    def __init__(self) -> None:
        self._kind: str | None = None
        self._detail: str | None = None

    def visit(self, row: dict) -> None:
        """Remember one row's kind and tool name."""
        kind = row.get("kind")
        if not kind:
            return
        self._kind = kind
        extra = row.get("extra") or {}
        tool = row.get("tool_name") or extra.get("tool_name")
        self._detail = str(tool) if tool else None

    def result(self) -> LastEvent:
        """Return the last seen kind and tool detail."""
        return LastEvent(self._kind, self._detail)


@dataclass(frozen=True)
class SessionResult:
    steps: int
    segments: int


class SessionVisitor(EventVisitor):
    """Counts session starts and distinct session ids."""

    def __init__(self) -> None:
        self._steps = 0
        self._segments: set[str] = set()

    def visit(self, row: dict) -> None:
        """Fold one row's session fields into the session counts."""
        if row.get("kind") == EventKind.SESSION_STARTED:
            self._steps += 1
        sid = row.get("session_id")
        if sid is not None:
            self._segments.add(sid)

    def result(self) -> SessionResult:
        """Return the step and segment counts."""
        return SessionResult(self._steps, len(self._segments))


class ErrorVisitor(EventVisitor):
    """Counts rows with kind "error"."""

    def __init__(self) -> None:
        self._errors = 0

    def visit(self, row: dict) -> None:
        """Count one row when it is an error."""
        if row.get("kind") == EventKind.ERROR:
            self._errors += 1

    def result(self) -> int:
        """Return the error count."""
        return self._errors


@dataclass
class ToolCallResult:
    tool_counts: dict[str, int]
    files_touched: dict[str, FileCounts]


class ToolCallVisitor(EventVisitor):
    """Counts tool calls (results preferred over uses) and files touched."""

    def __init__(self) -> None:
        self._tool_result_counts: dict[str, int] = {}
        self._tool_use_counts: dict[str, int] = {}
        self._files_touched: dict[str, FileCounts] = {}

    def visit(self, row: dict) -> None:
        """Fold one row's tool usage and file touches into the counts."""
        kind = row.get("kind")
        if kind == EventKind.TOOL_RESULT:
            tn = row.get("tool_name")
            if tn is not None:
                self._tool_result_counts[tn] = self._tool_result_counts.get(tn, 0) + 1
        elif kind == EventKind.TOOL_USE:
            tn = row.get("tool_name")
            if tn is not None:
                self._tool_use_counts[tn] = self._tool_use_counts.get(tn, 0) + 1
            op = _TOUCH_TOOLS.get(tn or "")
            if op:
                raw_data = row.get("raw") or {}
                inp = raw_data.get("input") or {}
                fpath = inp.get("file_path") or inp.get("path")
                if fpath:
                    fpath = str(fpath)
                    prev = self._files_touched.get(fpath)
                    if prev is None:
                        prev = FileCounts()
                    if op == "read":
                        self._files_touched[fpath] = FileCounts(
                            read=prev.read + 1, edit=prev.edit, write=prev.write
                        )
                    elif op == "edit":
                        self._files_touched[fpath] = FileCounts(
                            read=prev.read, edit=prev.edit + 1, write=prev.write
                        )
                    elif op == "write":
                        self._files_touched[fpath] = FileCounts(
                            read=prev.read, edit=prev.edit, write=prev.write + 1
                        )

    def result(self) -> ToolCallResult:
        """Return tool counts (results win over uses) and files touched."""
        counts = self._tool_result_counts if self._tool_result_counts else self._tool_use_counts
        return ToolCallResult(counts, self._files_touched)


@dataclass(frozen=True)
class UsageResult:
    output_tokens: int
    input_tokens: int
    cache_creation_tokens: int
    cache_read_tokens: int
    peak_context_tokens: int | None
    current_context_tokens: int | None


class UsageVisitor(EventVisitor):
    """Sums token usage and tracks peak/current context size."""

    def __init__(self) -> None:
        self._output = 0
        self._input = 0
        self._cache_creation = 0
        self._cache_read = 0
        self._peak: int | None = None
        self._current: int | None = None

    def visit(self, row: dict) -> None:
        """Fold one row's usage block into the token totals."""
        if row.get("kind") == EventKind.SESSION_ENDED:
            return
        usage = row.get("usage")
        if not isinstance(usage, dict):
            return
        self._output += safe_int(usage.get("output_tokens"))
        self._input += safe_int(usage.get("input_tokens"))
        self._cache_creation += safe_int(usage.get("cache_creation_input_tokens"))
        self._cache_read += safe_int(usage.get("cache_read_input_tokens"))
        ctx = (
            safe_int(usage.get("input_tokens"))
            + safe_int(usage.get("cache_creation_input_tokens"))
            + safe_int(usage.get("cache_read_input_tokens"))
        )
        if ctx > 0:
            self._current = ctx
            self._peak = ctx if self._peak is None else max(self._peak, ctx)

    def result(self) -> UsageResult:
        """Return the token totals and context sizes."""
        return UsageResult(
            self._output,
            self._input,
            self._cache_creation,
            self._cache_read,
            self._peak,
            self._current,
        )


@dataclass(frozen=True)
class RateLimitResult:
    limited: int
    events: list[dict]


class RateLimitVisitor(EventVisitor):
    """Collects rejected rate-limit events and their wait durations."""

    def __init__(self) -> None:
        self._limited = 0
        self._events: list[dict] = []

    def visit(self, row: dict) -> None:
        """Fold one row's rejected rate-limit info into the event list."""
        rate_info = row.get("rate_info")
        if row.get("kind") not in (EventKind.RATE_LIMIT, EventKind.RATE_LIMIT_INFO):
            return
        if not isinstance(rate_info, dict) or rate_info.get("status") != "rejected":
            return
        self._limited += 1
        ts_dt: datetime | None = None
        ts_str = row.get("ts")
        if isinstance(ts_str, str):
            ts_dt = parse_iso(ts_str)
        resets_at = rate_info.get("resets_at")
        duration_sec: float | None = None
        if resets_at is not None and ts_dt is not None:
            try:
                duration_sec = float(resets_at) - ts_dt.timestamp()
            except (TypeError, ValueError):
                duration_sec = None
        self._events.append(
            {
                "ts": ts_str,
                "provider": rate_info.get("provider") or "unknown",
                "duration_sec": duration_sec,
            }
        )

    def result(self) -> RateLimitResult:
        """Return the rejected count and event list."""
        return RateLimitResult(self._limited, self._events)


class ContextPressureVisitor(EventVisitor):
    """Records whether any row reported context pressure."""

    def __init__(self) -> None:
        self._pressure = False

    def visit(self, row: dict) -> None:
        """Latch once a context_pressure row is seen."""
        if row.get("kind") == TaskOutcome.CONTEXT_PRESSURE.value:
            self._pressure = True

    def result(self) -> bool:
        """Return whether context pressure was reported."""
        return self._pressure


# Every concern scan_rows covers, in visit order. scan_rows instantiates
# one of each per call, so visitors never share state between scans.
VISITORS: tuple[type[EventVisitor], ...] = (
    CountVisitor,
    TimingVisitor,
    LastEventVisitor,
    SessionVisitor,
    ErrorVisitor,
    ToolCallVisitor,
    UsageVisitor,
    RateLimitVisitor,
    ContextPressureVisitor,
)


def scan_rows(rows: Iterator[dict]) -> EventStats:
    """Single-pass scan of any row iterator into an EventStats.

    The shared core behind `scan` (all attempts) and `attempt_summary.py`
    (one attempt via `iter_attempt_events`), so the FileCounts/tool-count
    logic exists exactly once.
    """
    visitors = [visitor_cls() for visitor_cls in VISITORS]
    for row in rows:
        for visitor in visitors:
            visitor.visit(row)
    parts = {type(visitor): visitor.result() for visitor in visitors}
    timing: TimingResult = parts[TimingVisitor]
    last: LastEvent = parts[LastEventVisitor]
    session: SessionResult = parts[SessionVisitor]
    tools: ToolCallResult = parts[ToolCallVisitor]
    usage: UsageResult = parts[UsageVisitor]
    rate: RateLimitResult = parts[RateLimitVisitor]
    return EventStats(
        event_count=parts[CountVisitor],
        first_ts=timing.first_ts,
        last_ts=timing.last_ts,
        last_kind=last.kind,
        last_detail=last.detail,
        peak_context_tokens=usage.peak_context_tokens,
        current_context_tokens=usage.current_context_tokens,
        steps=session.steps,
        segments=session.segments,
        errors=parts[ErrorVisitor],
        tool_counts=tools.tool_counts,
        output_tokens=usage.output_tokens,
        input_tokens=usage.input_tokens,
        cache_creation_tokens=usage.cache_creation_tokens,
        cache_read_tokens=usage.cache_read_tokens,
        files_touched=tools.files_touched,
        hour_hist=timing.hour_hist,
        context_pressure=parts[ContextPressureVisitor],
        rate_limited=rate.limited,
        rate_limit_events=rate.events,
    )


def scan(task_dir: Path) -> EventStats:
    """Single-pass scan of every attempt's events.jsonl into an EventStats."""
    return scan_rows(iter_events(task_dir))


def _latest_events_file(task_dir: Path) -> Path:
    """The newest attempt's events.jsonl path (self-contained glob; see
    `_attempt_dirs_sorted` for why this doesn't import state.attempts)."""
    dirs = _attempt_dirs_sorted(task_dir)
    if not dirs:
        return task_dir / "attempts" / "0" / "events.jsonl"  # never exists; stat() -> OSError
    return dirs[-1] / "events.jsonl"


class EventScanCache:
    """Named owner of cached EventStats, keyed by task directory.

    Created by the caller that wants caching (state runtime_stats helpers, the API
    files endpoint, analytics records) and passed to ``scan_cached``; this
    module itself holds no shared state. Entries are keyed by the latest
    attempt's events.jsonl mtime+size, with a (-1.0, -1) sentinel when no
    attempt/events.jsonl exists (safe because a real mtime is
    large+positive). A new attempt (new file) also busts the cache since a
    freshly-created events.jsonl has a different mtime/size.
    """

    def __init__(self) -> None:
        """Start with an empty cache."""
        self._entries: dict[str, tuple[float, int, EventStats]] = {}

    def scan(self, task_dir: Path) -> EventStats:
        """Return cached stats, re-scanning only when the events file changed."""
        events_file = _latest_events_file(task_dir)
        cache_key = str(task_dir)
        try:
            st = events_file.stat()
            file_mtime: float = st.st_mtime
            file_size: int = st.st_size
        except OSError:
            file_mtime, file_size = -1.0, -1
        entry = self._entries.get(cache_key)
        if entry is not None and entry[0] == file_mtime and entry[1] == file_size:
            return entry[2]
        result = scan(task_dir)
        self._entries[cache_key] = (file_mtime, file_size, result)
        return result

    def clear(self) -> None:
        """Drop every cached entry."""
        self._entries.clear()


def scan_cached(task_dir: Path, cache: EventScanCache | None = None) -> EventStats:
    """Scan a task dir, reusing *cache* when one is passed in.

    With no cache this is a plain ``scan`` (always correct, never stored);
    owners that serve repeated reads create one ``EventScanCache`` and pass
    it here.
    """
    if cache is None:
        return scan(task_dir)
    return cache.scan(task_dir)
