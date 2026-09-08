"""Deterministic, no-LLM SUMMARY.md for one attempt.

`write_summary` is called from `orchestrator/reap.py` right after
`state.attempts.record_end`, alongside the RESULT.json/HANDOFF.md snapshots.
It never calls a model: everything is derived from this attempt's
`events.jsonl`, `launch.json`, `log.stderr`, the matching `attempts.jsonl`
row, and (optionally) `git log`/`git status` in the task's working
directory. The whole rendered file is hard-capped at ~4 KB.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from fleet.state import attempts as state_attempts
from fleet.state.events import iter_attempt_events, scan_rows

_MAX_CHARS = 4096
_STDERR_TAIL_LINES = 30
_LAST_TEXT_EVENTS = 5
_LAST_TEXT_MAX_CHARS = 400


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _attempt_row(task_dir: Path, n: int) -> dict:
    for row in state_attempts.load_attempts(task_dir):
        if row.get("n") == n:
            return row
    return {"n": n}


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


def _git_commits(workdir: Path | None, started_at: str | None, ended_at: str | None) -> list[str]:
    """`git log --oneline` between the attempt's start/end, or [] if not a repo."""
    if workdir is None or not started_at:
        return []
    cmd = ["git", "log", "--oneline", f"--since={started_at}"]
    if ended_at:
        cmd.append(f"--until={ended_at}")
    try:
        result = subprocess.run(
            cmd, cwd=workdir, capture_output=True, text=True, timeout=10, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.splitlines() if line.strip()]


def _git_status_short(workdir: Path | None) -> list[str]:
    if workdir is None:
        return []
    try:
        result = subprocess.run(
            ["git", "status", "--short"],
            cwd=workdir,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.splitlines() if line.strip()][:20]


def _render(
    *,
    n: int,
    launch: dict,
    row: dict,
    stats,
    commits: list[str],
    status_lines: list[str],
    last_error: dict | None,
    stderr_tail: list[str],
    last_texts: list[str],
) -> str:
    lines: list[str] = []
    lines.append(f"# Attempt {n} summary")
    lines.append("")
    lines.append(f"- kind: {launch.get('kind', 'work')}")
    lines.append(f"- launch mode: {launch.get('mode', 'unknown')}")
    lines.append(f"- coder/model: {row.get('coder')}/{row.get('model')}")
    lines.append(f"- started: {row.get('started_at')}")
    lines.append(f"- ended: {row.get('ended_at')}")
    lines.append(f"- duration_sec: {row.get('duration_sec')}")
    lines.append(f"- outcome: {row.get('outcome')} ({row.get('reason')})")
    lines.append(f"- exit_code: {row.get('exit_code')}")
    lines.append(
        f"- peak_context_tokens: {stats.peak_context_tokens} "
        f"({stats.output_tokens} output tokens)"
    )
    lines.append("")
    lines.append("## Files touched")
    if stats.files_touched:
        for path, counts in sorted(stats.files_touched.items()):
            lines.append(f"- {path}: read={counts.read} edit={counts.edit} write={counts.write}")
    else:
        lines.append("(none)")
    lines.append("")
    lines.append("## Tool calls")
    if stats.tool_counts:
        for name, count in sorted(stats.tool_counts.items()):
            lines.append(f"- {name}: {count}")
    else:
        lines.append("(none)")
    lines.append("")
    lines.append("## Commits")
    if commits:
        lines.extend(f"- {c}" for c in commits)
    else:
        lines.append("(none)")
    lines.append("")
    lines.append("## git status --short")
    if status_lines:
        lines.extend(status_lines)
    else:
        lines.append("(clean or not a git repo)")
    lines.append("")
    lines.append("## Last error event")
    lines.append(json.dumps(last_error)[:_LAST_TEXT_MAX_CHARS] if last_error else "(none)")
    lines.append("")
    lines.append(f"## Last {_STDERR_TAIL_LINES} lines of log.stderr")
    if stderr_tail:
        lines.extend(stderr_tail)
    else:
        lines.append("(empty)")
    lines.append("")
    lines.append(f"## Last {_LAST_TEXT_EVENTS} assistant_text events")
    if last_texts:
        for i, t in enumerate(last_texts, 1):
            lines.append(f"{i}. {t[:_LAST_TEXT_MAX_CHARS]}")
    else:
        lines.append("(none)")
    return "\n".join(lines)


def write_summary(task_dir: Path, n: int, workdir: Path | None) -> Path:
    """Render and write `attempts/<n>/SUMMARY.md`; return its path.

    Deterministic and side-effect-free besides the write: no model call, no
    network. Truncated to ~4 KB as a final safety net regardless of how much
    the sections above produced.
    """
    attempt_dir = state_attempts.attempt_dir(task_dir, n)
    attempt_dir.mkdir(parents=True, exist_ok=True)

    launch = _read_json(attempt_dir / "launch.json")
    row = _attempt_row(task_dir, n)
    stats = scan_rows(iter_attempt_events(task_dir, n))

    events = list(iter_attempt_events(task_dir, n))
    last_error = next(
        (e for e in reversed(events) if e.get("kind") == "error"), None
    )
    last_texts = [
        _extract_text(e) for e in events if e.get("kind") == "assistant_text"
    ][-_LAST_TEXT_EVENTS:]

    commits = _git_commits(workdir, row.get("started_at"), row.get("ended_at"))
    status_lines = _git_status_short(workdir)
    stderr_tail = _read_stderr_tail(attempt_dir, _STDERR_TAIL_LINES)

    text = _render(
        n=n,
        launch=launch,
        row=row,
        stats=stats,
        commits=commits,
        status_lines=status_lines,
        last_error=last_error,
        stderr_tail=stderr_tail,
        last_texts=last_texts,
    )
    text = text[:_MAX_CHARS]

    out_path = attempt_dir / "SUMMARY.md"
    out_path.write_text(text, encoding="utf-8")
    return out_path
