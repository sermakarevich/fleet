"""Deterministic, no-LLM per-attempt summary, derived on demand (ADR 0004).

`summarize` builds an `AttemptSummary` from one attempt's `run.json`
(including its `launch` record), `events.jsonl`, the matching
`attempts.jsonl` row, and the `RESULT.json` snapshot — no model call, no
network. `render_markdown` renders it, hard-capped at ~4 KB. Nothing is
stored: readers (`orchestrator/triage.py`, `workers/compact.py`,
`serve/api/tasks.py`, `state/task_summary.py`, `cli/tasks.py`) compute it
when they need it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

from fleet.core.task import AttemptKind, EventKind
from fleet.state import attempts as state_attempts
from fleet.state import paths as state_paths
from fleet.state.events import iter_attempt_events, stats_from_rows
from fleet.state.run_file import RunRecord

_MAX_CHARS = 4096
_STDERR_TAIL_LINES = 30
_LAST_TEXT_EVENTS = 5
_LAST_TEXT_MAX_CHARS = 400


@dataclass(frozen=True, slots=True)
class AttemptRow:
    """One merged attempts.jsonl row, typed at the read edge."""

    n: int = 0
    kind: str = "work"
    mode: str = "unknown"
    coder: str | None = None
    model: str | None = None
    started_at: str | None = None
    ended_at: str | None = None
    duration_sec: float | None = None
    outcome: str | None = None
    reason: str | None = None
    exit_code: int | None = None
    action: str | None = None
    worker: str | None = None

    @classmethod
    def from_dict(cls, row: dict) -> AttemptRow:
        """Build a row from a raw journal dict, ignoring unknown keys."""
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in row.items() if k in known})

    def get(self, key: str, default: Any = None) -> Any:
        """Dict-style read so existing callers keep working."""
        return getattr(self, key, default) if hasattr(self, key) else default

    def __getitem__(self, key: str) -> Any:
        """Dict-style index so existing callers keep working."""
        try:
            return getattr(self, key)
        except AttributeError:
            raise KeyError(key) from None


@dataclass(frozen=True, slots=True)
class AttemptSummary:
    """Derived facts about one attempt (never stored on disk)."""

    n: int
    kind: str = "work"
    mode: str = "unknown"
    coder: str | None = None
    model: str | None = None
    started_at: str | None = None
    ended_at: str | None = None
    duration_sec: float | None = None
    outcome: str | None = None
    reason: str | None = None
    exit_code: int | None = None
    cli_compactions: int = 0
    peak_context_tokens: int | None = None
    output_tokens: int | None = None
    files_touched: dict = field(default_factory=dict)
    tool_counts: dict = field(default_factory=dict)
    result: dict | None = None
    last_error: dict | None = None
    stderr_tail: list[str] = field(default_factory=list)
    last_texts: list[str] = field(default_factory=list)


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _attempt_row(task_dir: Path, n: int) -> AttemptRow:
    """The journal row for attempt *n* as a typed record."""
    for row in state_attempts.load_attempts(task_dir):
        if row.get("n") == n:
            return AttemptRow.from_dict(row)
    return AttemptRow(n=n)


def _extract_text(row: dict) -> str:
    """Best-effort plain-text excerpt from one assistant_text event.

    Coders shape `raw` differently (claude nests content blocks under
    ``message.content``; others put a flat ``text`` field); this tries the
    common shapes and falls back to a compact JSON dump so the summary never
    crashes on an unfamiliar coder.
    """
    raw = row.get("raw")
    if not isinstance(raw, dict):
        return ""
    msg = raw.get("message")
    if isinstance(msg, dict):
        content = msg.get("content")
        if isinstance(content, list):
            texts = [
                b.get("text", "")
                for b in content
                if isinstance(b, dict) and b.get("type") == "text"
            ]
            joined = "\n".join(t for t in texts if t)
            if joined:
                return joined
    for key in ("text", "message"):
        val = raw.get(key)
        if isinstance(val, str) and val:
            return val
    return json.dumps(raw)[:_LAST_TEXT_MAX_CHARS]


def _read_stderr_tail(attempt_dir: Path, n_lines: int) -> list[str]:
    path = attempt_dir / "log.stderr"
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    lines = text.splitlines()
    return lines[-n_lines:]


def summarize(task_dir: Path, n: int) -> AttemptSummary:
    """Compute the derived summary for attempt *n*. Pure read path."""
    attempt_dir = state_paths.attempt_dir(task_dir, n)
    run = RunRecord.load(attempt_dir)
    launch = run.launch if run is not None and isinstance(run.launch, dict) else {}
    row = _attempt_row(task_dir, n)
    stats = stats_from_rows(iter_attempt_events(task_dir, n))

    events = list(iter_attempt_events(task_dir, n))
    last_error = next((e for e in reversed(events) if e.get("kind") == EventKind.ERROR), None)
    last_texts = [_extract_text(e) for e in events if e.get("kind") == EventKind.ASSISTANT_TEXT][
        -_LAST_TEXT_EVENTS:
    ]

    stderr_tail = _read_stderr_tail(attempt_dir, _STDERR_TAIL_LINES)
    # CLI-side auto-compactions: the claude PreCompact hook touches
    # .compacted in the attempt dir each time it fires.
    cli_compactions = 1 if (attempt_dir / ".compacted").exists() else 0
    result = _read_json(attempt_dir / "RESULT.json") or None

    return AttemptSummary(
        n=n,
        kind=str(launch.get("kind") or row.get("kind") or AttemptKind.WORK.value),
        mode=str(launch.get("mode") or "unknown"),
        coder=row.get("coder"),
        model=row.get("model"),
        started_at=row.get("started_at"),
        ended_at=row.get("ended_at"),
        duration_sec=row.get("duration_sec"),
        outcome=row.get("outcome"),
        reason=row.get("reason"),
        exit_code=row.get("exit_code"),
        cli_compactions=cli_compactions,
        peak_context_tokens=stats.peak_context_tokens,
        output_tokens=stats.output_tokens,
        files_touched=dict(stats.files_touched),
        tool_counts=dict(stats.tool_counts),
        result=result,
        last_error=last_error,
        stderr_tail=stderr_tail,
        last_texts=last_texts,
    )


def render_markdown(summary: AttemptSummary) -> str:
    """Render *summary* as markdown, hard-capped at ~4 KB."""
    lines: list[str] = []
    lines.append(f"# Attempt {summary.n} summary")
    lines.append("")
    lines.append(f"- kind: {summary.kind}")
    lines.append(f"- launch mode: {summary.mode}")
    lines.append(f"- coder/model: {summary.coder}/{summary.model}")
    lines.append(f"- started: {summary.started_at}")
    lines.append(f"- ended: {summary.ended_at}")
    lines.append(f"- duration_sec: {summary.duration_sec}")
    lines.append(f"- outcome: {summary.outcome} ({summary.reason})")
    lines.append(f"- exit_code: {summary.exit_code}")
    lines.append(f"- cli_compactions: {summary.cli_compactions}")
    lines.append(
        f"- peak_context_tokens: {summary.peak_context_tokens} "
        f"({summary.output_tokens} output tokens)"
    )
    if summary.result is not None:
        lines.append(
            f"- declared result: {summary.result.get('status')}: {summary.result.get('summary')}"
        )
    lines.append("")
    lines.append("## Files touched")
    if summary.files_touched:
        for path, counts in sorted(summary.files_touched.items()):
            lines.append(f"- {path}: read={counts.read} edit={counts.edit} write={counts.write}")
    else:
        lines.append("(none)")
    lines.append("")
    lines.append("## Tool calls")
    if summary.tool_counts:
        for name, count in sorted(summary.tool_counts.items()):
            lines.append(f"- {name}: {count}")
    else:
        lines.append("(none)")
    lines.append("")
    lines.append("## Declared RESULT.json")
    if summary.result is not None:
        lines.append(json.dumps(summary.result)[:_LAST_TEXT_MAX_CHARS])
    else:
        lines.append("(none)")
    lines.append("")
    lines.append("## Last error event")
    lines.append(
        json.dumps(summary.last_error)[:_LAST_TEXT_MAX_CHARS] if summary.last_error else "(none)"
    )
    lines.append("")
    lines.append(f"## Last {_STDERR_TAIL_LINES} lines of log.stderr")
    if summary.stderr_tail:
        lines.extend(summary.stderr_tail)
    else:
        lines.append("(empty)")
    lines.append("")
    lines.append(f"## Last {_LAST_TEXT_EVENTS} assistant_text events")
    if summary.last_texts:
        for i, t in enumerate(summary.last_texts, 1):
            lines.append(f"{i}. {t[:_LAST_TEXT_MAX_CHARS]}")
    else:
        lines.append("(none)")
    return "\n".join(lines)[:_MAX_CHARS]
