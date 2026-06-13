import os
import subprocess
from pathlib import Path

import pytest

from fleet.worktree import (
    create_worktree,
    is_committed_clean,
    remove_worktree,
    worktree_isolation_enabled,
    worktree_path,
)


def _git_init(path: Path) -> None:
    """Create a minimal git repo at path."""
    subprocess.run(
        ["git", "init", "-b", "main"], cwd=path, capture_output=True, check=True
    )
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=test@test.com",
            "-c",
            "user.name=test",
            "commit",
            "--allow-empty",
            "-m",
            "init",
        ],
        cwd=path,
        capture_output=True,
        check=True,
    )


@pytest.fixture()
def git_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path / ".fleet"))
    _git_init(tmp_path)
    return tmp_path


class TestWorktreePath:
    def test_default_path(self):
        path = worktree_path("task-123")
        assert path == Path.home() / ".fleet" / "worktrees" / "task-123"

    def test_custom_fleet_home(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("FLEET_HOME", "/custom/home")
        path = worktree_path("task-456")
        assert path == Path("/custom/home").resolve() / "worktrees" / "task-456"


class TestWorktreeIsolationEnabled:
    def test_default_off(self):
        assert worktree_isolation_enabled() is False

    def test_env_gated(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("FLEET_WORKTREE_ISOLATION", "1")
        assert worktree_isolation_enabled() is True

    def test_other_values_off(self, monkeypatch: pytest.MonkeyPatch):
        for val in ["0", "yes", ""]:
            monkeypatch.setenv("FLEET_WORKTREE_ISOLATION", val)
            assert worktree_isolation_enabled() is False


class TestCreateWorktree:
    def test_creates_dir_and_checkout_branch(self, git_repo: Path):
        task_id = "test-wt-1"
        path = create_worktree(git_repo, task_id)

        assert path.exists()

        # Verify branch
        branch = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
        )
        assert branch.stdout.strip() == f"fleet/{task_id}"

    def test_idempotent(self, git_repo: Path):
        task_id = "test-wt-2"
        path1 = create_worktree(git_repo, task_id)
        path2 = create_worktree(git_repo, task_id)
        assert path1 == path2
        assert path2.exists()


class TestIsCommittedClean:
    def test_false_right_after_create(self, git_repo: Path):
        task_id = "test-clean-1"
        wt = create_worktree(git_repo, task_id)
        assert is_committed_clean(wt) is False

    def test_true_after_commit(self, git_repo: Path):
        task_id = "test-clean-2"
        wt = create_worktree(git_repo, task_id)

        test_file = wt / "hello.txt"
        test_file.write_text("hello")
        subprocess.run(
            ["git", "-C", str(wt), "add", "hello.txt"], capture_output=True, check=True
        )
        subprocess.run(
            [
                "git",
                "-C",
                str(wt),
                "-c",
                "user.email=test@test.com",
                "-c",
                "user.name=test",
                "commit",
                "-m",
                "wip",
            ],
            capture_output=True,
            check=True,
        )

        assert is_committed_clean(wt) is True

    def test_false_with_dirty_files(self, git_repo: Path):
        task_id = "test-clean-3"
        wt = create_worktree(git_repo, task_id)

        test_file = wt / "hello.txt"
        test_file.write_text("hello")
        subprocess.run(
            ["git", "-C", str(wt), "add", "hello.txt"], capture_output=True, check=True
        )
        subprocess.run(
            [
                "git",
                "-C",
                str(wt),
                "-c",
                "user.email=test@test.com",
                "-c",
                "user.name=test",
                "commit",
                "-m",
                "wip",
            ],
            capture_output=True,
            check=True,
        )

        (wt / "hello.txt").write_text("dirty")
        assert is_committed_clean(wt) is False


class TestRemoveWorktree:
    def test_removes_worktree(self, git_repo: Path):
        task_id = "test-rm-1"
        wt = create_worktree(git_repo, task_id)
        assert wt.exists()

        remove_worktree(git_repo, task_id)
        assert not wt.exists()

    def test_safe_when_already_gone(self, git_repo: Path):
        task_id = "test-rm-2"
        remove_worktree(git_repo, task_id)
        # Should not raise
