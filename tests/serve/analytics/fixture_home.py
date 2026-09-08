"""Deterministic analytics fixture home shared by the analytics tests.

Builds six tasks with fixed timestamps (no clock dependence): a closed
success, a failed task with a rejected rate-limit event, a blocked task
with an unknown coder, an active task with no events, a closed task whose
journal released without closing (noclose), and a closed task whose
journal ended in context_pressure. ``compute_summary(home, 0)`` over this
home is fully deterministic and pinned by the snapshot fixture.
"""

from __future__ import annotations

import json
from pathlib import Path


def _ev(ts: str, kind: str, **fields) -> str:
    """One event line."""
    row: dict = {"ts": ts, "kind": kind}
    row.update(fields)
    return json.dumps(row)


def _make_task(
    tasks_root: Path,
    task_id: str,
    *,
    status: str,
    coder: str = "claude",
    model: str = "sonnet",
    cwd: str = "/proj-a",
    created_at: str | None = None,
) -> Path:
    """Create a task dir with task.json; return its path."""
    task_dir = tasks_root / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    data: dict = {
        "id": task_id,
        "title": f"Task {task_id}",
        "status": status,
        "cwd": cwd,
        "coder": coder,
        "model": model,
        "priority": 1,
    }
    if created_at is not None:
        data["created_at"] = created_at
    (task_dir / "task.json").write_text(json.dumps(data), "utf-8")
    return task_dir


def _write_events(task_dir: Path, lines: list[str]) -> None:
    """Write event lines to attempts/1/events.jsonl."""
    attempt_dir = task_dir / "attempts" / "1"
    attempt_dir.mkdir(parents=True, exist_ok=True)
    (attempt_dir / "events.jsonl").write_text("\n".join(lines) + "\n", "utf-8")


def _write_attempts(task_dir: Path, outcome: str, action: str) -> None:
    """Write a one-attempt journal ending in *outcome* (one line per event)."""
    stamp = "2025-06-04T10:00:00+00:00"
    (task_dir / "attempts.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"event": "start", "n": 1, "ts": stamp}),
                json.dumps(
                    {
                        "event": "end",
                        "n": 1,
                        "ts": stamp,
                        "outcome": outcome,
                        "exit_code": 0,
                        "reason": "fixture",
                        "action": action,
                    }
                ),
            ]
        )
        + "\n",
        "utf-8",
    )


def build_fixture_home(home: Path) -> Path:
    """Create the fixture tasks under *home* and return *home*."""
    tasks_root = home / "tasks"

    alpha = _make_task(
        tasks_root, "task-alpha", status="closed", created_at="2025-05-30T09:00:00+00:00"
    )
    _write_events(
        alpha,
        [
            _ev("2025-06-01T10:00:00Z", "session_started", session_id="s1"),
            _ev(
                "2025-06-01T11:00:00Z",
                "tool_result",
                tool_name="Read",
                usage={
                    "input_tokens": 100,
                    "output_tokens": 200,
                    "cache_creation_input_tokens": 50,
                    "cache_read_input_tokens": 10,
                },
            ),
            _ev("2025-06-01T12:00:00Z", "error"),
        ],
    )

    beta = _make_task(
        tasks_root, "task-beta", status="failed", coder="claude", model="opus", cwd="/proj-b"
    )
    _write_events(
        beta,
        [
            _ev("2025-06-02T10:00:00Z", "session_started", session_id="s2"),
            _ev("2025-06-02T12:00:00Z", "rate_limit", rate_info={"status": "rejected"}),
            _ev(
                "2025-06-02T13:00:00Z",
                "tool_result",
                tool_name="Edit",
                usage={"input_tokens": 150, "output_tokens": 300},
            ),
        ],
    )

    gamma = _make_task(
        tasks_root, "task-gamma", status="blocked", coder="", model="", cwd="/proj-a"
    )
    _write_events(gamma, [_ev("2025-06-03T10:00:00Z", "session_started", session_id="s3")])

    _make_task(tasks_root, "task-delta", status="in_progress", cwd="/proj-c")

    eps = _make_task(tasks_root, "task-eps", status="closed", cwd="/proj-a")
    _write_events(
        eps,
        [
            _ev("2025-06-04T10:00:00Z", "session_started", session_id="s4"),
            _ev(
                "2025-06-04T11:00:00Z",
                "tool_result",
                tool_name="Write",
                usage={"input_tokens": 25, "output_tokens": 50},
            ),
        ],
    )
    _write_attempts(eps, "success", "release")

    zeta = _make_task(tasks_root, "task-zeta", status="closed", cwd="/proj-b")
    _write_events(zeta, [_ev("2025-06-05T10:00:00Z", "session_started", session_id="s5")])
    _write_attempts(zeta, "context_pressure", "release")

    return home
