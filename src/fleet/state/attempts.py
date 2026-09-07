import json
from datetime import UTC, datetime
from pathlib import Path


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
    for line in text.splitlines():
        line = line.strip()
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
    for line in text.splitlines():
        line = line.strip()
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
            if n > current:
                current = n
    return current


def record_start(task_dir: Path, *, coder: str | None, model: str | None) -> int:
    """Append a start line and return its attempt number."""
    task_dir.mkdir(parents=True, exist_ok=True)
    n = _count_starts(task_dir) + 1
    entry = {
        "event": "start",
        "n": n,
        "ts": _utc_now_iso(),
        "coder": coder,
        "model": model,
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
) -> None:
    """Append an end line for the current attempt."""
    task_dir.mkdir(parents=True, exist_ok=True)
    n = _current_n(task_dir)
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
    for line in text.splitlines():
        line = line.strip()
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
            n = int(obj.get("n"))
        except (TypeError, ValueError):
            continue
        entry = by_n.setdefault(n, {"n": n})
        if event == "start":
            entry["started_at"] = obj.get("ts")
            entry["coder"] = obj.get("coder")
            entry["model"] = obj.get("model")
        elif event == "end":
            entry["ended_at"] = obj.get("ts")
            entry["outcome"] = obj.get("outcome")
            entry["exit_code"] = obj.get("exit_code")
            entry["reason"] = obj.get("reason")
            entry["action"] = obj.get("action")
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
