import contextlib
import json
from datetime import UTC, datetime
from pathlib import Path

from fleet.state.paths import attempt_dir_path


def _attempts_path(task_dir: Path) -> Path:
    return task_dir / "attempts.jsonl"


def _utc_now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


def _count_starts(task_dir: Path) -> int:
    path = _attempts_path(task_dir)
    if not path.exists():
        return 0
    count = 0
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return 0
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except (ValueError, json.JSONDecodeError):
            continue
        if isinstance(obj, dict) and obj.get("event") == "start":
            count += 1
    return count


def _current_n(task_dir: Path) -> int:
    """Return the highest start N seen so far, or 0 if none."""
    path = _attempts_path(task_dir)
    if not path.exists():
        return 0
    current = 0
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return 0
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except (ValueError, json.JSONDecodeError):
            continue
        if isinstance(obj, dict) and obj.get("event") == "start":
            try:
                n = int(obj.get("n", 0))
            except (TypeError, ValueError):
                continue
            current = max(current, n)
    return current


def _max_n(task_dir: Path) -> int:
    """Highest N seen in any start or end line, or 0 if none."""
    path = _attempts_path(task_dir)
    if not path.exists():
        return 0
    current = 0
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return 0
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except (ValueError, json.JSONDecodeError):
            continue
        if isinstance(obj, dict) and obj.get("event") in ("start", "end", "unblock"):
            try:
                n = int(obj.get("n", 0))
            except (TypeError, ValueError):
                continue
            current = max(current, n)
    return current


def current_attempt_n(task_dir: Path) -> int:
    """Public alias for the highest start N seen so far, or 0 if none.

    Used by callers (e.g. reap.py) that need "the attempt that just ended"
    after the fact, without re-deriving the counting logic themselves.
    """
    return _current_n(task_dir)


def attempt_dir(task_dir: Path, n: int) -> Path:
    """The on-disk directory for attempt *n* of this task."""
    return attempt_dir_path(task_dir, n)


def latest_attempt_dir(task_dir: Path, before_n: int | None = None) -> Path | None:
    """Return the directory of the most recent attempt, or None if there is none.

    When *before_n* is given, returns the highest attempt strictly less than
    it (used when planning attempt N to find the last *completed* attempt,
    since attempt N's own row/dir may already exist by the time this runs).
    When omitted, returns the highest attempt number recorded at all (used by
    tailing/log/stall/leases, which want "the currently running or most
    recently run attempt").
    """
    rows = load_attempts(task_dir)
    if before_n is not None:
        rows = [a for a in rows if a["n"] < before_n]
    if not rows:
        return None
    # A compaction job records its own row *after* the work attempt it serves
    # has started, so the highest number can belong to an already finished
    # helper while the real session is still writing to a lower-numbered
    # directory. Whoever is still running is "the latest" for tailing, stall
    # detection and leases; fall back to the highest number otherwise.
    running = [a["n"] for a in rows if a.get("started_at") and not a.get("ended_at")]
    if running:
        return attempt_dir_path(task_dir, max(running))
    return attempt_dir_path(task_dir, max(a["n"] for a in rows))


def record_start(
    task_dir: Path,
    *,
    coder: str | None,
    model: str | None,
    worker: str | None = None,
    kind: str = "work",
) -> int:
    """Append a start line and return its attempt number.

    *kind* is "work" for normal attempts and "compact" for the compaction
    job (workers/compact.py), which gets its own attempt row so it shows in
    the Attempts timeline and is costed like any attempt.
    """
    task_dir.mkdir(parents=True, exist_ok=True)
    n = _max_n(task_dir) + 1
    entry = {
        "event": "start",
        "n": n,
        "ts": _utc_now_iso(),
        "coder": coder,
        "model": model,
        "worker": worker,
        "kind": kind,
    }
    with _attempts_path(task_dir).open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
    return n


def record_end(
    task_dir: Path,
    *,
    outcome: str,
    exit_code: int | None,
    reason: str,
    action: str,
    n: int | None = None,
) -> None:
    """Append an end line for an attempt.

    *n* defaults to the current start number (the attempt that just ended);
    pass it explicitly when closing an older attempt — e.g. reap closing the
    outer work attempt after a compaction step journaled its own newer row.
    When no start was ever recorded (unit tests driving reap directly),
    allocate a fresh n so repeated ends don't collapse into one row.
    """
    task_dir.mkdir(parents=True, exist_ok=True)
    if n is None:
        n = _current_n(task_dir)
        if n == 0:
            n = _max_n(task_dir) + 1
    entry = {
        "event": "end",
        "n": n,
        "ts": _utc_now_iso(),
        "outcome": outcome,
        "exit_code": exit_code,
        "reason": reason,
        "action": action,
    }
    with _attempts_path(task_dir).open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def set_worker(task_dir: Path, n: int, worker: str) -> None:
    """Tag attempt *n*'s start line with the worker name that ran it.

    Spawn records the start before the worker is planned, so it calls this
    right after `workers.select_worker`. Best effort: a missing file or a
    missing start line is a no-op. The journal is rewritten atomically so
    concurrent readers never see a half-written file.
    """
    path = _attempts_path(task_dir)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return
    changed = False
    out_lines: list[str] = []
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        try:
            obj = json.loads(stripped) if stripped else None
        except (ValueError, json.JSONDecodeError):
            obj = None
        if isinstance(obj, dict) and obj.get("event") == "start" and obj.get("n") == n:
            obj["worker"] = worker
            out_lines.append(json.dumps(obj))
            changed = True
        else:
            out_lines.append(raw_line)
    if not changed:
        return
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
        tmp.replace(path)
    except OSError:
        with contextlib.suppress(OSError):
            tmp.unlink(missing_ok=True)


def record_unblock(task_dir: Path, note: str | None = None) -> int:
    """Append an "unblock" row: an operator released a blocked task.

    The row gets its own n so it shows in the Attempts timeline
    (kind "unblock", outcome "unblocked") and, being neither a failure nor
    any other round category, ends every retry streak in
    core/retry_policy: the next attempt starts counting from zero.
    """
    task_dir.mkdir(parents=True, exist_ok=True)
    n = _max_n(task_dir) + 1
    entry = {
        "event": "unblock",
        "n": n,
        "ts": _utc_now_iso(),
        "reason": note or "unblocked by operator",
    }
    with _attempts_path(task_dir).open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
    return n


def _parse_ts(ts: str | None) -> datetime | None:
    if not ts or not isinstance(ts, str):
        return None
    try:
        dt = datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def load_attempts(task_dir: Path) -> list[dict]:
    """Merge start/end lines by n into per-attempt dicts sorted by n."""
    path = _attempts_path(task_dir)
    if not path.exists():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    by_n: dict[int, dict] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except (ValueError, json.JSONDecodeError):
            continue
        if not isinstance(obj, dict):
            continue
        event = obj.get("event")
        try:
            n = int(obj.get("n"))  # type: ignore[arg-type]  # untyped attempts.jsonl row; bead 18 types AttemptRow
        except (TypeError, ValueError):
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
        else:
            continue
    result: list[dict] = []
    for n in sorted(by_n):
        entry = by_n[n]
        merged = {
            "n": n,
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
        start_dt = _parse_ts(merged["started_at"])
        end_dt = _parse_ts(merged["ended_at"])
        if start_dt is not None and end_dt is not None:
            merged["duration_sec"] = (end_dt - start_dt).total_seconds()
        result.append(merged)
    return result


def restart_count(task_dir: Path) -> int:
    """Number of starts minus 1, minimum 0."""
    return max(_count_starts(task_dir) - 1, 0)


def last_attempt(task_dir: Path) -> dict | None:
    """Last element of load_attempts or None."""
    items = load_attempts(task_dir)
    if not items:
        return None
    return items[-1]
