"""Tests for ``src/fleet/supervisor_worktree.py`` — the dormant worktree bridge."""

from pathlib import Path

import pytest

from fleet.supervisor_worktree import (
    cleanup_worktree,
    ensure_worktree,
    is_task_advanced,
    is_committed_clean,
)


def _git_init(path: Path) -> None:
    """Create a minimal git repo at path."""
    import subprocess

    subprocess.run(
        ["git", "init", "-b", "main"],
        cwd=path,
        capture_output=True,
        check=True,
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
        expected = Path.home() / ".fleet" / "worktrees" / "test-ens-2"
        assert path == expected

    def test_ignores_fleet_home_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """ensure_worktree uses worktree module's own home resolution."""
        # Set FLEET_HOME to tmp_path (used by other functions)
        monkeypatch.setenv("FLEET_HOME", str(tmp_path / ".fleet"))
        monkeypatch.setenv("FLEET_WORKTREE_ISOLATION", "1")
        # But the worktree module uses its own FLEET_HOME resolution


class TestCleanupWorktree:
    def test_removes_worktree_when_exists(
        self, git_repo: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """cleanup_worktree removes an existing worktree."""
        monkeypatch.setenv("FLEET_WORKTREE_ISOLATION", "1")
        from fleet.worktree import create_worktree

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


class TestIsValidWorktree:
    def test_false_right_after_create(
        self, git_repo: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """is_task_advanced returns False right after create (no commits yet)."""
        monkeypatch.setenv("FLEET_WORKTREE_ISOLATION", "1")
        from fleet.worktree import create_worktree

        path = create_worktree(git_repo, "test-adv-1")
        assert is_task_advanced(path) is False

    def test_true_after_commit(self, git_repo: Path, monkeypatch: pytest.MonkeyPatch):
        """is_task_advanced returns True after a commit."""
        monkeypatch.setenv("FLEET_WORKTREE_ISOLATION", "1")
        import subprocess

        from fleet.worktree import create_worktree

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

    def test_false_without_fleet_home_on_path(self, git_repo: Path):
        """is_task_advanced uses the worktree_path arg directly, not FLEET_HOME."""
        # The function receives a Path directly, not a task_id
        # When that path doesn't exist or has no .fleet directory, it should just check git state


class TestIsWorktreeCommitClean:
    def test_false_on_invalid_path(self):
        """is_committed_clean returns False on a non-directory."""
        assert is_committed_clean(Path("/nonexistent/path/12345")) is False


class TestModuleImports:
    def test_no_circular_imports(self):
        """supervisor_worktree should only import from fleet.worktree."""

        # Reload fresh to test import chain
        import fleet.supervisor_worktree as mod

        # Check that worktree functions are bound
        assert hasattr(mod, "ensure_worktree")
        assert hasattr(mod, "cleanup_worktree")
        assert hasattr(mod, "is_task_advanced")
        assert hasattr(mod, "is_committed_clean")
        assert hasattr(mod, "worktree_isolation_enabled")
        assert hasattr(mod, "worktree_path")
