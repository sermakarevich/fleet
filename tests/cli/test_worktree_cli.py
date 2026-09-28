"""Tests for `fleet worktree merge|drop` (unit under test: cli/worktree.py).

`merge_task_worktree`/`drop_task_worktree` are monkeypatched: `merge --json`
prints the outcome object and exits 0/1, the human line reads
`merged fleet/<id> into <base>` / `merge failed: <message>`; `drop` matches.
"""

from __future__ import annotations

import json
from pathlib import Path

from fleet.cli.main import app
from fleet.orchestrator.worktree_merge import MergeOutcome
from tests.cli.conftest import runner


def _ok(task_id: str = "run-1.build", *, merged: bool = True) -> MergeOutcome:
    """Success outcome: merged into main (or a plain ok when not merged)."""
    return MergeOutcome(
        ok=True,
        task_id=task_id,
        repo_root="/repo",
        base_ref="main",
        branch=f"fleet/{task_id}",
        merged=merged,
        message=f"merged fleet/{task_id} into main" if merged else "not isolated",
    )


def _failed(task_id: str = "run-1.build") -> MergeOutcome:
    """Refusal outcome: dirty base, nothing merged."""
    return MergeOutcome(
        ok=False,
        task_id=task_id,
        repo_root="/repo",
        base_ref="main",
        branch=f"fleet/{task_id}",
        message="base repo dirty; merge manually",
    )


def test_merge_json_ok(tmp_path: Path, monkeypatch) -> None:
    """`merge <id> --json` prints the outcome object and exits 0."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    monkeypatch.setattr(
        "fleet.cli.worktree.worktree_merge.merge_task_worktree", lambda *a, **k: _ok()
    )
    result = runner.invoke(app, ["worktree", "merge", "run-1.build", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["merged"] is True
    assert payload["task_id"] == "run-1.build"
    assert payload["branch"] == "fleet/run-1.build"


def test_merge_json_failure_exits_1(tmp_path: Path, monkeypatch) -> None:
    """`merge <id> --json` on a refusal prints the outcome and exits 1."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    monkeypatch.setattr(
        "fleet.cli.worktree.worktree_merge.merge_task_worktree", lambda *a, **k: _failed()
    )
    result = runner.invoke(app, ["worktree", "merge", "run-1.build", "--json"])
    assert result.exit_code == 1, result.output
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert "base repo dirty" in payload["message"]


def test_merge_human_lines(tmp_path: Path, monkeypatch) -> None:
    """Human output is one `merged ...` line on success, `merge failed:` else."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    monkeypatch.setattr(
        "fleet.cli.worktree.worktree_merge.merge_task_worktree", lambda *a, **k: _ok()
    )
    ok_result = runner.invoke(app, ["worktree", "merge", "run-1.build"])
    assert ok_result.exit_code == 0, ok_result.output
    assert ok_result.stdout.strip() == "merged fleet/run-1.build into main"

    monkeypatch.setattr(
        "fleet.cli.worktree.worktree_merge.merge_task_worktree", lambda *a, **k: _failed()
    )
    fail_result = runner.invoke(app, ["worktree", "merge", "run-1.build"])
    assert fail_result.exit_code == 1, fail_result.output
    assert fail_result.stdout.strip() == "merge failed: base repo dirty; merge manually"


def test_merge_passes_keep_branch(tmp_path: Path, monkeypatch) -> None:
    """--keep-branch reaches merge_task_worktree as keep_branch=True."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    seen: dict = {}

    def fake(fleet_home, config, task_id, *, keep_branch=False):  # noqa: ANN001, ANN002, ANN003, ANN202
        seen["keep_branch"] = keep_branch
        return _ok(task_id)

    monkeypatch.setattr("fleet.cli.worktree.worktree_merge.merge_task_worktree", fake)
    result = runner.invoke(app, ["worktree", "merge", "run-1.build", "--keep-branch"])
    assert result.exit_code == 0, result.output
    assert seen == {"keep_branch": True}


def test_drop_json_ok(tmp_path: Path, monkeypatch) -> None:
    """`drop <id> --json` prints the outcome object and exits 0."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    monkeypatch.setattr(
        "fleet.cli.worktree.worktree_merge.drop_task_worktree", lambda *a, **k: _ok(merged=False)
    )
    result = runner.invoke(app, ["worktree", "drop", "run-1.build", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["merged"] is False


def test_drop_human_line(tmp_path: Path, monkeypatch) -> None:
    """Human drop output prints the outcome message on one line."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    monkeypatch.setattr(
        "fleet.cli.worktree.worktree_merge.drop_task_worktree", lambda *a, **k: _ok(merged=False)
    )
    result = runner.invoke(app, ["worktree", "drop", "run-1.build"])
    assert result.exit_code == 0, result.output
    assert result.stdout.strip() == "not isolated"
