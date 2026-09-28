"""Tests for `fleet blocked`, `fleet ready`, `fleet block` and `fleet ignore`.

Tmp fleet home holds two task folders (one blocked with a reason, one
blocked without) plus a FakeQueue snapshot; `fleet blocked --json` lists only
the first with the eleven expected keys, and `fleet ignore` writes
`ignore_until` into task.json. The fake queue also holds three ready beads
(one routable, one with a future `retry_after`, one ignored); `fleet ready
--json` lists only the first with the seven bead-flow keys, and `fleet block`
records the reason through `set_blocked`.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from typer.testing import CliRunner

from fleet.beads.client import BdError
from fleet.cli.main import app
from fleet.core.iso import parse_iso
from fleet.core.retry_policy import rounds_for_history
from fleet.core.task import Task
from fleet.state.task_meta import TaskMeta
from tests.cli.conftest import runner

BLOCKED_AT = "2026-09-01T00:00:00+00:00"
REASON = "retry limit (3) exhausted; last failure: boom in worker extra detail tail"


class FakeQueue:
    """Blocked snapshot plus task.json-backed ignore writes."""

    def __init__(self, fleet_home: Path) -> None:
        self.fleet_home = fleet_home
        self.blocked_calls: list[tuple[str, str]] = []
        future = (datetime.now(tz=UTC) + timedelta(hours=1)).isoformat()
        self.tasks = {
            "t1": Task(id="t1", title="Bead t1", description=None, status="blocked"),
            "t2": Task(id="t2", title="Bead t2", description=None, status="blocked"),
            "r1": Task(
                id="r1",
                title="Bead r1",
                description="Do the thing",
                status="open",
                cwd="/repo",
                coder="opencode",
                model="muse-spark",
                isolation="worktree",
            ),
            "r2": Task(
                id="r2",
                title="Bead r2",
                description="Waiting",
                status="open",
                retry_after=future,
            ),
            "r3": Task(
                id="r3",
                title="Bead r3",
                description="Ignored",
                status="open",
                ignore_until="forever",
            ),
        }

    def list_blocked(self, limit: int = 100) -> list[Task]:
        """Blocked beads in snapshot order."""
        return [t for t in self.tasks.values() if t.status == "blocked"][:limit]

    def list_ready(self, limit: int = 100) -> list[Task]:
        """Open beads in snapshot order (retry/ignore filtering lives in cli/blocked.py)."""
        return [t for t in self.tasks.values() if t.status == "open"][:limit]

    def get(self, task_id: str) -> Task:
        """One bead, raising BdError when unknown."""
        try:
            return self.tasks[task_id]
        except KeyError as exc:
            raise BdError(f"bd show {task_id}: no issue returned") from exc

    def set_ignore(self, task_id: str, ignore_until: str) -> None:
        """Persist the ignore stamp into the bead's task.json."""
        self.get(task_id)
        TaskMeta.update(self.fleet_home / "tasks" / task_id, ignore_until=ignore_until)

    def set_blocked(self, task_id: str, reason: str) -> None:
        """Record the block reason for later assertion."""
        self.get(task_id)
        self.blocked_calls.append((task_id, reason))


def _task(tmp_path: Path, task_id: str, **meta) -> None:
    """Write tasks/<id>/task.json with a blocked base plus *meta*."""
    task_dir = tmp_path / "tasks" / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    base = {"id": task_id, "title": f"Title {task_id}", "status": "blocked", "cwd": "/repo"}
    base.update(meta)
    (task_dir / "task.json").write_text(json.dumps(base), encoding="utf-8")


def _use_home(tmp_path: Path, monkeypatch) -> FakeQueue:
    """Point FLEET_HOME at tmp_path with two task folders and a fake queue."""
    _task(
        tmp_path,
        "t1",
        blocked_reason=REASON,
        blocked_at=BLOCKED_AT,
        coder="claude",
        model="opus",
    )
    _task(tmp_path, "t2")
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    fake = FakeQueue(tmp_path)
    monkeypatch.setattr("fleet.cli.bootstrap.queue", lambda fleet_home: fake)
    return fake


def test_blocked_json_lists_only_reasoned_bead_with_all_keys(tmp_path: Path, monkeypatch) -> None:
    """--json lists t1 (reason) with the eleven keys, skipping t2 (no reason)."""
    _use_home(tmp_path, monkeypatch)
    result = runner.invoke(app, ["blocked", "--json"])
    assert result.exit_code == 0, result.output
    [item] = json.loads(result.stdout)
    assert set(item) == {
        "id",
        "title",
        "blocked_reason",
        "blocked_at",
        "cwd",
        "coder",
        "model",
        "rounds",
        "result_status",
        "task_dir",
        "stderr_tail",
    }
    assert item["id"] == "t1"
    assert item["blocked_reason"] == REASON
    assert item["blocked_at"] == BLOCKED_AT
    assert item["cwd"] == "/repo"
    assert item["coder"] == "claude"
    assert item["model"] == "opus"
    assert item["rounds"] == str(rounds_for_history([]))
    assert item["result_status"] == ""
    assert item["task_dir"] == str((tmp_path / "tasks" / "t1").absolute())
    assert item["stderr_tail"] == ""
    assert all(isinstance(value, str) for value in item.values())


def test_blocked_table_shows_reason_preview(tmp_path: Path, monkeypatch) -> None:
    """Human table shows t1 with the reason preview, not t2 or the full reason."""
    _use_home(tmp_path, monkeypatch)
    wide = CliRunner(env={"COLUMNS": "200"})
    result = wide.invoke(app, ["blocked"])
    assert result.exit_code == 0, result.output
    assert "t1" in result.output
    assert "t2" not in result.output
    assert REASON[:60] in result.output


def test_blocked_skips_active_ignore(tmp_path: Path, monkeypatch) -> None:
    """A bead ignored via `fleet ignore` disappears from the next listing."""
    _use_home(tmp_path, monkeypatch)
    ignored = runner.invoke(app, ["ignore", "t1", "--hours", "2"])
    assert ignored.exit_code == 0, ignored.output
    result = runner.invoke(app, ["blocked", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == []


def test_ignore_writes_ignore_until(tmp_path: Path, monkeypatch) -> None:
    """`fleet ignore t1 --hours 2` stores a future ISO stamp in task.json."""
    _use_home(tmp_path, monkeypatch)
    before = datetime.now(tz=UTC)
    result = runner.invoke(app, ["ignore", "t1", "--hours", "2"])
    assert result.exit_code == 0, result.output
    raw = json.loads((tmp_path / "tasks" / "t1" / "task.json").read_text(encoding="utf-8"))
    parsed = parse_iso(raw["ignore_until"])
    assert parsed is not None
    assert parsed > before + timedelta(hours=1)


def test_ignore_unknown_bead_is_not_found(tmp_path: Path, monkeypatch) -> None:
    """Ignoring an unknown bead exits NOT_FOUND."""
    _use_home(tmp_path, monkeypatch)
    result = runner.invoke(app, ["ignore", "nope", "--hours", "2"])
    assert result.exit_code == 3


def test_ignore_non_positive_hours_is_usage(tmp_path: Path, monkeypatch) -> None:
    """--hours 0 exits USAGE without touching task.json."""
    _use_home(tmp_path, monkeypatch)
    result = runner.invoke(app, ["ignore", "t1", "--hours", "0"])
    assert result.exit_code == 2
    raw = json.loads((tmp_path / "tasks" / "t1" / "task.json").read_text(encoding="utf-8"))
    assert "ignore_until" not in raw


def test_ready_json_lists_ready_bead_with_seven_keys(tmp_path: Path, monkeypatch) -> None:
    """--json lists r1 with the seven bead-flow keys, skipping r2 (retry) and r3 (ignore)."""
    _use_home(tmp_path, monkeypatch)
    result = runner.invoke(app, ["ready", "--json"])
    assert result.exit_code == 0, result.output
    [item] = json.loads(result.stdout)
    assert set(item) == {"id", "title", "description", "coder", "model", "cwd", "isolation"}
    assert item["id"] == "r1"
    assert item["title"] == "Bead r1"
    assert item["description"] == "Do the thing"
    assert item["coder"] == "opencode"
    assert item["model"] == "muse-spark"
    assert item["cwd"] == "/repo"
    assert item["isolation"] == "worktree"
    assert all(isinstance(value, str) for value in item.values())


def test_ready_table_shows_coder_cwd_title(tmp_path: Path, monkeypatch) -> None:
    """Human table shows r1 with coder/cwd/title, not the skipped beads."""
    _use_home(tmp_path, monkeypatch)
    wide = CliRunner(env={"COLUMNS": "200"})
    result = wide.invoke(app, ["ready"])
    assert result.exit_code == 0, result.output
    assert "r1" in result.output
    assert "opencode" in result.output
    assert "/repo" in result.output
    assert "Bead r1" in result.output
    assert "r2" not in result.output
    assert "r3" not in result.output


def test_block_calls_set_blocked_with_reason(tmp_path: Path, monkeypatch) -> None:
    """`fleet block r1 --reason x` records the reason and prints the confirmation."""
    fake = _use_home(tmp_path, monkeypatch)
    result = runner.invoke(app, ["block", "r1", "--reason", "stuck on review"])
    assert result.exit_code == 0, result.output
    assert fake.blocked_calls == [("r1", "stuck on review")]
    assert "Blocked r1: stuck on review" in result.output


def test_block_empty_reason_is_usage(tmp_path: Path, monkeypatch) -> None:
    """An empty --reason exits USAGE without calling set_blocked."""
    fake = _use_home(tmp_path, monkeypatch)
    result = runner.invoke(app, ["block", "r1", "--reason", ""])
    assert result.exit_code == 2
    assert fake.blocked_calls == []


def test_block_unknown_bead_is_not_found(tmp_path: Path, monkeypatch) -> None:
    """Blocking an unknown bead exits NOT_FOUND."""
    _use_home(tmp_path, monkeypatch)
    result = runner.invoke(app, ["block", "nope", "--reason", "x"])
    assert result.exit_code == 3
