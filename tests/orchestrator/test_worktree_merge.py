"""Tests for orchestrator/worktree_merge.py (unit under test: worktree_merge.py).

A real temporary git repo (init, one commit on `main`), a fake fleet home
and a task dir whose task.json holds repo_root/base_ref/worktree_path (the
worktree is created with `worktree.create_worktree` and a file is committed
on the branch).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from fleet.core.config import RuntimeConfig
from fleet.orchestrator import worktree, worktree_merge
from fleet.orchestrator.worktree_merge import MergeOutcome


def _git(path: Path, *args: str) -> None:
    """Run one git command in *path*; raise when it fails."""
    subprocess.run(["git", "-C", str(path), *args], capture_output=True, check=True)


def _git_init(path: Path) -> None:
    """Init a repo on `main` with one empty commit and a test identity."""
    subprocess.run(["git", "init", "-b", "main"], cwd=path, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"], cwd=path, capture_output=True, check=False
    )
    subprocess.run(
        ["git", "config", "user.name", "test"], cwd=path, capture_output=True, check=False
    )
    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", "init"],
        cwd=path,
        capture_output=True,
        check=True,
    )


def _commit(path: Path, name: str, content: str, msg: str = "wip") -> None:
    """Write *name*, stage it, and commit in *path*."""
    (Path(path) / name).write_text(content)
    _git(path, "add", name)
    _git(
        path,
        "-c",
        "user.email=test@test.com",
        "-c",
        "user.name=test",
        "commit",
        "-m",
        msg,
    )


def _setup_repo(tmp_path: Path) -> tuple[Path, Path]:
    """Fake fleet home plus a one-commit repo on `main`."""
    fleet_home = tmp_path / ".fleet"
    fleet_home.mkdir(exist_ok=True)
    repo = tmp_path / "repo"
    repo.mkdir(exist_ok=True)
    if not (repo / ".git").exists():
        _git_init(repo)
    return fleet_home, repo


def _isolate(
    fleet_home: Path, repo: Path, task_id: str, base_ref: str = "main"
) -> tuple[Path, Path]:
    """Write task.json isolation info; return (task_dir, worktree)."""
    task_dir = fleet_home / "tasks" / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    wt = worktree.create_worktree(repo, task_id, base_ref=base_ref, fleet_home=fleet_home)
    (task_dir / "task.json").write_text(
        json.dumps(
            {
                "id": task_id,
                "repo_root": str(repo),
                "base_ref": base_ref,
                "worktree_path": str(wt),
            }
        )
    )
    return task_dir, wt


def _branch_exists(repo: Path, task_id: str) -> bool:
    """True when `fleet/<task id>` still resolves in *repo*."""
    result = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--verify", f"refs/heads/fleet/{task_id}"],
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def _meta_of(task_dir: Path) -> dict:
    """Parsed task.json of one task dir."""
    return json.loads((task_dir / "task.json").read_text(encoding="utf-8"))


def _make_conflict(fleet_home: Path, repo: Path, task_id: str) -> tuple[Path, Path]:
    """Branch and main edits to the same tracked file (a real conflict)."""
    _commit(repo, "tracked.txt", "line1\nline2\n", msg="initial")
    task_dir, wt = _isolate(fleet_home, repo, task_id)
    (wt / "tracked.txt").write_text("branch version\nline2\n")
    _git(wt, "add", "tracked.txt")
    _git(
        wt,
        "-c",
        "user.email=test@test.com",
        "-c",
        "user.name=test",
        "commit",
        "-m",
        "branch edit",
    )
    (repo / "tracked.txt").write_text("main version\nline2\n")
    _git(repo, "add", "tracked.txt")
    _git(
        repo,
        "-c",
        "user.email=test@test.com",
        "-c",
        "user.name=test",
        "commit",
        "-m",
        "main edit",
    )
    return task_dir, wt


class TestMergeSuccess:
    def test_merge_moves_file_cleans_up_and_clears_info(self, tmp_path: Path) -> None:
        """Merge puts the file on main, removes the worktree/branch, clears task.json."""
        fleet_home, repo = _setup_repo(tmp_path)
        task_id = "run-1.build"
        task_dir, wt = _isolate(fleet_home, repo, task_id)
        _commit(wt, "feature.txt", "feature content")

        outcome = worktree_merge.merge_task_worktree(fleet_home, RuntimeConfig(), task_id)

        assert outcome == MergeOutcome(
            ok=True,
            task_id=task_id,
            repo_root=str(repo),
            base_ref="main",
            branch=f"fleet/{task_id}",
            merged=True,
            message=f"merged fleet/{task_id} into main",
        )
        assert (repo / "feature.txt").read_text() == "feature content"
        assert not wt.exists()
        assert not _branch_exists(repo, task_id)
        meta = _meta_of(task_dir)
        assert "repo_root" not in meta
        assert "base_ref" not in meta
        assert "worktree_path" not in meta

    def test_second_merge_reports_no_isolation_info(self, tmp_path: Path) -> None:
        """Merging twice: the second call finds cleared isolation info."""
        fleet_home, repo = _setup_repo(tmp_path)
        task_id = "run-1.build"
        _, wt = _isolate(fleet_home, repo, task_id)
        _commit(wt, "feature.txt", "feature content")

        first = worktree_merge.merge_task_worktree(fleet_home, RuntimeConfig(), task_id)
        assert first.ok
        second = worktree_merge.merge_task_worktree(fleet_home, RuntimeConfig(), task_id)

        assert not second.ok
        assert second.message == f"no isolation info for {task_id}"
        assert not second.merged

    def test_keep_branch_keeps_the_branch(self, tmp_path: Path) -> None:
        """keep_branch=True merges but leaves fleet/<id> in place."""
        fleet_home, repo = _setup_repo(tmp_path)
        task_id = "run-1.build"
        _, wt = _isolate(fleet_home, repo, task_id)
        _commit(wt, "feature.txt", "feature content")

        outcome = worktree_merge.merge_task_worktree(
            fleet_home, RuntimeConfig(), task_id, keep_branch=True
        )

        assert outcome.ok and outcome.merged
        assert (repo / "feature.txt").read_text() == "feature content"
        assert not wt.exists()
        assert _branch_exists(repo, task_id)

    def test_unknown_id_reports_no_isolation_info(self, tmp_path: Path) -> None:
        """A task dir without isolation info merges nothing and removes nothing."""
        fleet_home, _ = _setup_repo(tmp_path)

        outcome = worktree_merge.merge_task_worktree(fleet_home, RuntimeConfig(), "nope.step")

        assert not outcome.ok
        assert outcome.message == "no isolation info for nope.step"


class TestMergeRefusals:
    def test_no_commit_worktree_removed_branch_kept(self, tmp_path: Path) -> None:
        """Nothing ahead of base: worktree gone, branch kept, not-ahead message."""
        fleet_home, repo = _setup_repo(tmp_path)
        task_id = "run-1.build"
        task_dir, wt = _isolate(fleet_home, repo, task_id)

        outcome = worktree_merge.merge_task_worktree(fleet_home, RuntimeConfig(), task_id)

        assert not outcome.ok
        assert outcome.message == "worktree not clean/ahead of main; merge manually"
        assert not wt.exists()
        assert _branch_exists(repo, task_id)
        assert _meta_of(task_dir)["repo_root"] == str(repo)

    def test_conflict_keeps_branch_reports_files(self, tmp_path: Path) -> None:
        """Clashing main commit: conflict files reported, branch still exists."""
        fleet_home, repo = _setup_repo(tmp_path)
        task_id = "run-1.build"
        _, wt = _make_conflict(fleet_home, repo, task_id)

        outcome = worktree_merge.merge_task_worktree(fleet_home, RuntimeConfig(), task_id)

        assert not outcome.ok
        assert not outcome.merged
        assert outcome.conflict_files == ("tracked.txt",)
        assert outcome.message == f"merge conflict into main; branch fleet/{task_id} kept"
        assert _branch_exists(repo, task_id)
        assert not wt.exists()

    def test_dirty_base_keeps_worktree(self, tmp_path: Path) -> None:
        """Uncommitted base change: nothing touched, worktree still exists."""
        fleet_home, repo = _setup_repo(tmp_path)
        task_id = "run-1.build"
        _, wt = _isolate(fleet_home, repo, task_id)
        _commit(wt, "f.txt", "work")
        (repo / "uncommitted.txt").write_text("x")
        _git(repo, "add", "uncommitted.txt")
        (repo / "uncommitted.txt").write_text("modified")

        outcome = worktree_merge.merge_task_worktree(fleet_home, RuntimeConfig(), task_id)

        assert not outcome.ok
        assert outcome.message == "base repo dirty; merge manually"
        assert wt.exists()
        assert _branch_exists(repo, task_id)

    def test_repo_root_gone(self, tmp_path: Path) -> None:
        """Isolation info pointing at a deleted repo: repo_root gone message."""
        fleet_home, repo = _setup_repo(tmp_path)
        task_id = "run-1.build"
        _, _ = _isolate(fleet_home, repo, task_id)
        gone = fleet_home / "tasks" / task_id / "task.json"
        meta = json.loads(gone.read_text(encoding="utf-8"))
        meta["repo_root"] = str(tmp_path / "deleted-repo")
        gone.write_text(json.dumps(meta), encoding="utf-8")

        outcome = worktree_merge.merge_task_worktree(fleet_home, RuntimeConfig(), task_id)

        assert not outcome.ok
        assert outcome.message.startswith("repo_root gone (")


class TestPostMergeCommand:
    def test_failing_command_blocks_with_tail(self, tmp_path: Path) -> None:
        """post_merge_command=false: merge done but outcome failed with the tail."""
        fleet_home, repo = _setup_repo(tmp_path)
        task_id = "run-1.build"
        _, wt = _isolate(fleet_home, repo, task_id)
        _commit(wt, "f.txt", "work")
        config = RuntimeConfig(post_merge_command="false")

        outcome = worktree_merge.merge_task_worktree(fleet_home, config, task_id)

        assert not outcome.ok
        assert outcome.message.startswith("post-merge command failed:\n")
        assert not wt.exists()

    def test_empty_command_merges(self, tmp_path: Path) -> None:
        """Empty post_merge_command skips validation and merges."""
        fleet_home, repo = _setup_repo(tmp_path)
        task_id = "run-1.build"
        _, wt = _isolate(fleet_home, repo, task_id)
        _commit(wt, "f.txt", "work")

        outcome = worktree_merge.merge_task_worktree(
            fleet_home, RuntimeConfig(post_merge_command=""), task_id
        )

        assert outcome.ok and outcome.merged


class TestDrop:
    def test_drop_removes_worktree_and_branch(self, tmp_path: Path) -> None:
        """Drop cleans the worktree, deletes the branch, clears task.json."""
        fleet_home, repo = _setup_repo(tmp_path)
        task_id = "run-1.build"
        task_dir, wt = _isolate(fleet_home, repo, task_id)
        _commit(wt, "f.txt", "work")

        outcome = worktree_merge.drop_task_worktree(fleet_home, task_id)

        assert outcome.ok
        assert not outcome.merged
        assert not wt.exists()
        assert not _branch_exists(repo, task_id)
        assert "worktree_path" not in _meta_of(task_dir)
        assert not (repo / "f.txt").exists()

    def test_drop_unknown_id_is_noop(self, tmp_path: Path) -> None:
        """Dropping a never-isolated id succeeds with the not-isolated message."""
        fleet_home, _ = _setup_repo(tmp_path)

        outcome = worktree_merge.drop_task_worktree(fleet_home, "nope.step")

        assert outcome.ok
        assert outcome.message == "not isolated"
