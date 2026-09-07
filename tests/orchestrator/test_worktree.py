import subprocess
from pathlib import Path

import pytest

from fleet.orchestrator.worktree import (
    cleanup_worktree,
    create_worktree,
    ensure_worktree,
    is_committed_clean,
    is_task_advanced,
    merge_to_base,
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


class TestMergeToBase:
    def _set_user(self, path: Path) -> None:
        subprocess.run(
            [
                "git",
                "-c",
                "user.email=test@test.com",
                "-c",
                "user.name=test",
                "commit",
                "-m",
                "wip",
            ],
            cwd=path,
            capture_output=True,
            check=False,
        )

    def test_clean_merge(self, git_repo: Path):
        task_id = "test-merge-1"
        branch = f"fleet/{task_id}"

        # Create branch from main and add a new file on it
        subprocess.run(
            ["git", "-C", str(git_repo), "checkout", "-b", branch],
            capture_output=True,
            check=True,
        )
        new_file = git_repo / "feature.txt"
        new_file.write_text("feature content")
        subprocess.run(
            [
                "git",
                "-C",
                str(git_repo),
                "-c",
                "user.email=test@test.com",
                "-c",
                "user.name=test",
                "add",
                "feature.txt",
            ],
            capture_output=True,
            check=True,
        )
        subprocess.run(
            [
                "git",
                "-C",
                str(git_repo),
                "-c",
                "user.email=test@test.com",
                "-c",
                "user.name=test",
                "commit",
                "-m",
                "add feature",
            ],
            capture_output=True,
            check=True,
        )

        # Switch back to main
        subprocess.run(
            ["git", "-C", str(git_repo), "checkout", "main"],
            capture_output=True,
            check=True,
        )

        result = merge_to_base(git_repo, task_id)
        assert result.ok is True
        assert result.conflict is False
        assert new_file.exists()
        assert new_file.read_text() == "feature content"

    def test_conflict(self, git_repo: Path):
        task_id = "test-merge-2"
        branch = f"fleet/{task_id}"

        # Create a tracked file on main
        tracked_file = git_repo / "tracked.txt"
        tracked_file.write_text("line1\nline2\n")
        subprocess.run(
            [
                "git",
                "-C",
                str(git_repo),
                "-c",
                "user.email=test@test.com",
                "-c",
                "user.name=test",
                "add",
                "tracked.txt",
            ],
            capture_output=True,
            check=True,
        )
        subprocess.run(
            [
                "git",
                "-C",
                str(git_repo),
                "-c",
                "user.email=test@test.com",
                "-c",
                "user.name=test",
                "commit",
                "-m",
                "initial content",
            ],
            capture_output=True,
            check=True,
        )

        # Create branch from main
        subprocess.run(
            ["git", "-C", str(git_repo), "checkout", "-b", branch],
            capture_output=True,
            check=True,
        )
        # Edit line 1 on the branch
        tracked_file.write_text("branch version\nline2\n")
        subprocess.run(
            [
                "git",
                "-C",
                str(git_repo),
                "-c",
                "user.email=test@test.com",
                "-c",
                "user.name=test",
                "add",
                "tracked.txt",
            ],
            capture_output=True,
            text=True,
        )
        subprocess.run(
            [
                "git",
                "-C",
                str(git_repo),
                "-c",
                "user.email=test@test.com",
                "-c",
                "user.name=test",
                "commit",
                "-m",
                "edit on branch",
            ],
            capture_output=True,
            check=True,
        )

        # Switch back to main and edit the same line differently
        subprocess.run(
            ["git", "-C", str(git_repo), "checkout", "main"],
            capture_output=True,
            check=True,
        )
        tracked_file.write_text("main version\nline2\n")
        subprocess.run(
            [
                "git",
                "-C",
                str(git_repo),
                "-c",
                "user.email=test@test.com",
                "-c",
                "user.name=test",
                "add",
                "tracked.txt",
            ],
            capture_output=True,
            check=True,
        )
        subprocess.run(
            [
                "git",
                "-C",
                str(git_repo),
                "-c",
                "user.email=test@test.com",
                "-c",
                "user.name=test",
                "commit",
                "-m",
                "edit on main",
            ],
            capture_output=True,
            check=True,
        )

        result = merge_to_base(git_repo, task_id)
        assert result.ok is False
        assert result.conflict is True

        # Verify merge was aborted - status should be clean
        status = subprocess.run(
            ["git", "-C", str(git_repo), "status", "--porcelain"],
            capture_output=True,
            text=True,
        )
        assert status.stdout.strip() == ""


class TestEnsureWorktree:
    def test_returns_none_when_disabled(self):
        """ensure_worktree returns None when isolation env var is not set."""
        result = ensure_worktree(Path("/fake"), "task-1")
        assert result is None

    def test_calls_create_worktree_when_enabled(
        self, git_repo: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """ensure_worktree creates a worktree when isolation is enabled."""
        monkeypatch.setenv("FLEET_WORKTREE_ISOLATION", "1")
        path = ensure_worktree(git_repo, "test-ens-1")
        assert path is not None
        assert path.exists()

    def test_returns_worktree_path(
        self, git_repo: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """ensure_worktree returns the expected path."""
        monkeypatch.setenv("FLEET_WORKTREE_ISOLATION", "1")
        path = ensure_worktree(git_repo, "test-ens-2")
        expected = worktree_path("test-ens-2")
        assert path == expected


class TestCleanupWorktree:
    def test_removes_worktree_when_exists(
        self, git_repo: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """cleanup_worktree removes an existing worktree."""
        monkeypatch.setenv("FLEET_WORKTREE_ISOLATION", "1")
        create_worktree(git_repo, "test-cleanup-1")
        path = Path.home() / ".fleet" / "worktrees" / "test-cleanup-1"

        cleanup_worktree(git_repo, "test-cleanup-1")
        assert not path.exists()

    def test_safe_when_worktree_gone(self, git_repo: Path):
        """cleanup_worktree does not raise when worktree is already gone."""
        cleanup_worktree(git_repo, "nonexistent-task")
        # Should not raise

    def test_safe_when_isolation_disabled(self, git_repo: Path):
        """cleanup_worktree is safe when isolation is not enabled."""
        cleanup_worktree(git_repo, "test-cleanup-2")
        # Should not raise


class TestIsTaskAdvanced:
    def test_false_right_after_create(
        self, git_repo: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """is_task_advanced returns False right after create (no commits yet)."""
        monkeypatch.setenv("FLEET_WORKTREE_ISOLATION", "1")
        path = create_worktree(git_repo, "test-adv-1")
        assert is_task_advanced(path) is False

    def test_true_after_commit(self, git_repo: Path, monkeypatch: pytest.MonkeyPatch):
        """is_task_advanced returns True after a commit."""
        monkeypatch.setenv("FLEET_WORKTREE_ISOLATION", "1")
        path = create_worktree(git_repo, "test-adv-2")

        test_file = path / "hello.txt"
        test_file.write_text("hello")
        subprocess.run(
            ["git", "-C", str(path), "add", "hello.txt"],
            capture_output=True,
            check=True,
        )
        subprocess.run(
            [
                "git",
                "-C",
                str(path),
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

        assert is_task_advanced(path) is True
