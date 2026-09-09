"""Git-aware worktree isolation: detect, create, merge, dirty-base block."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from fleet.orchestrator import worktree
from fleet.orchestrator.worktree import has_uncommitted_changes


def _git(path: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(path), *args], capture_output=True, text=True, check=True
    )


def _git_init(path: Path, branch: str = "main") -> None:
    subprocess.run(["git", "init", "-b", branch], cwd=path, capture_output=True, check=True)
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


def _commit(path: Path, name: str, content: str = "x", msg: str = "wip") -> None:
    (Path(path) / name).write_text(content)
    _git(path, "add", name)
    _git(path, "-c", "user.email=test@test.com", "-c", "user.name=test", "commit", "-m", msg)


@pytest.fixture()
def git_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path / ".fleet"))
    repo = tmp_path / "myrepo"
    repo.mkdir()
    _git_init(repo)
    return repo


@pytest.fixture()
def fleet_home(tmp_path: Path) -> Path:
    fleet_home = tmp_path / ".fleet"
    fleet_home.mkdir(exist_ok=True)
    return fleet_home


class TestDetectRepoRoot:
    def test_detects_toplevel_from_root(self, git_repo: Path):
        assert worktree.detect_repo_root(git_repo) == git_repo

    def test_detects_toplevel_from_subdir(self, git_repo: Path):
        sub = git_repo / "a" / "b"
        sub.mkdir(parents=True)
        assert worktree.detect_repo_root(sub) == git_repo

    def test_non_git_dir_returns_none(self, tmp_path: Path):
        plain = tmp_path / "plain"
        plain.mkdir()
        assert worktree.detect_repo_root(plain) is None

    def test_missing_dir_returns_none(self, tmp_path: Path):
        assert worktree.detect_repo_root(tmp_path / "nope") is None


class TestResolveBaseRef:
    def test_current_branch_when_no_remote(self, git_repo: Path):
        assert worktree.resolve_base_ref(git_repo) == "main"

    def test_custom_branch(self, tmp_path: Path):
        repo = tmp_path / "r2"
        repo.mkdir()
        _git_init(repo, branch="trunk")
        assert worktree.resolve_base_ref(repo) == "trunk"

    def test_falls_back_to_main(self, tmp_path: Path):
        assert worktree.resolve_base_ref(tmp_path) == "main"


class TestCreateWorktree:
    def test_location_includes_repo_name(
        self, git_repo: Path, fleet_home: Path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("FLEET_HOME", str(fleet_home))
        path = worktree.create_worktree(git_repo, "t-1", base_ref="main", fleet_home=fleet_home)
        assert path == fleet_home / "worktrees" / "myrepo-t-1"
        assert path.is_dir()

    def test_branch_name(self, git_repo: Path, fleet_home: Path):
        wt = worktree.create_worktree(git_repo, "t-2", base_ref="main", fleet_home=fleet_home)
        out = subprocess.run(
            ["git", "-C", str(wt), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert out.stdout.strip() == "fleet/t-2"

    def test_reused_across_attempts(self, git_repo: Path, fleet_home: Path):
        p1 = worktree.create_worktree(git_repo, "t-3", base_ref="main", fleet_home=fleet_home)
        p2 = worktree.create_worktree(git_repo, "t-3", base_ref="main", fleet_home=fleet_home)
        assert p1 == p2

    def test_avoids_collisions_across_repos(
        self, tmp_path: Path, fleet_home: Path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("FLEET_HOME", str(fleet_home))
        a = tmp_path / "repoA"
        b = tmp_path / "repoB"
        a.mkdir()
        b.mkdir()
        _git_init(a)
        _git_init(b)
        pa = worktree.create_worktree(a, "same", base_ref="main", fleet_home=fleet_home)
        pb = worktree.create_worktree(b, "same", base_ref="main", fleet_home=fleet_home)
        assert pa != pb
        assert pa.name == "repoA-same"
        assert pb.name == "repoB-same"


class TestIsCommittedClean:
    def test_false_right_after_create(self, git_repo: Path, fleet_home: Path):
        wt = worktree.create_worktree(git_repo, "c-1", base_ref="main", fleet_home=fleet_home)
        assert worktree.is_committed_clean(wt, base_ref="main") is False

    def test_true_after_commit(self, git_repo: Path, fleet_home: Path):
        wt = worktree.create_worktree(git_repo, "c-2", base_ref="main", fleet_home=fleet_home)
        _commit(wt, "hello.txt", "hello")
        assert worktree.is_committed_clean(wt, base_ref="main") is True

    def test_false_with_dirty_files(self, git_repo: Path, fleet_home: Path):
        wt = worktree.create_worktree(git_repo, "c-3", base_ref="main", fleet_home=fleet_home)
        _commit(wt, "hello.txt", "hello")
        (wt / "hello.txt").write_text("dirty")
        assert worktree.is_committed_clean(wt, base_ref="main") is False


class TestMergeFastForward:
    def test_clean_ff_merge(self, git_repo: Path, fleet_home: Path):
        wt = worktree.create_worktree(git_repo, "m-1", base_ref="main", fleet_home=fleet_home)
        _commit(wt, "feature.txt", "feature content")
        result = worktree.merge_to_base(git_repo, "m-1", base_ref="main")
        assert result.ok is True
        assert (git_repo / "feature.txt").read_text() == "feature content"

    def test_conflict_blocks(self, git_repo: Path, fleet_home: Path):
        _commit(git_repo, "tracked.txt", "line1\nline2\n", msg="initial")
        wt = worktree.create_worktree(git_repo, "m-2", base_ref="main", fleet_home=fleet_home)
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
        (git_repo / "tracked.txt").write_text("main version\nline2\n")
        _git(git_repo, "add", "tracked.txt")
        _git(
            git_repo,
            "-c",
            "user.email=test@test.com",
            "-c",
            "user.name=test",
            "commit",
            "-m",
            "main edit",
        )
        result = worktree.merge_to_base(git_repo, "m-2", base_ref="main")
        assert result.ok is False
        assert result.conflict is True
        status = subprocess.run(
            ["git", "-C", str(git_repo), "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert status.stdout.strip() == ""

    def test_dirty_base_refuses_without_touching(self, git_repo: Path, fleet_home: Path):
        wt = worktree.create_worktree(git_repo, "m-3", base_ref="main", fleet_home=fleet_home)
        _commit(wt, "f.txt", "work")
        # Dirty the base checkout (unstaged change).
        (git_repo / "dirty.txt").write_text("uncommitted")
        _git(git_repo, "add", "dirty.txt")
        (git_repo / "dirty.txt").write_text("modified-after-add")
        head_before = _git(git_repo, "rev-parse", "HEAD").stdout.strip()
        result = worktree.merge_to_base(git_repo, "m-3", base_ref="main")
        assert result.ok is False
        assert "dirty" in result.message
        assert _git(git_repo, "rev-parse", "HEAD").stdout.strip() == head_before


class TestPostMergeCommand:
    def test_empty_command_skips(self, tmp_path: Path):
        ok, out = worktree.run_post_merge_command("", tmp_path)
        assert ok is True
        assert out == ""

    def test_success(self, tmp_path: Path):
        ok, _ = worktree.run_post_merge_command("true", tmp_path)
        assert ok is True

    def test_failure_returns_tail(self, tmp_path: Path):
        ok, tail = worktree.run_post_merge_command(
            "python3 -c 'import sys; print(\"boom\"); sys.exit(1)'", tmp_path
        )
        assert ok is False
        assert "boom" in tail


class TestRemoveAndBranch:
    def test_remove_then_delete_branch(self, git_repo: Path, fleet_home: Path):
        wt = worktree.create_worktree(git_repo, "r-1", base_ref="main", fleet_home=fleet_home)
        assert wt.exists()
        worktree.remove_worktree(git_repo, "r-1", wt)
        assert not wt.exists()
        worktree.delete_branch(git_repo, "r-1")
        assert (
            subprocess.run(
                ["git", "-C", str(git_repo), "rev-parse", "--verify", "fleet/r-1"],
                capture_output=True,
                check=False,
            ).returncode
            != 0
        )

    def test_remove_safe_when_gone(self, git_repo: Path, fleet_home: Path):
        worktree.remove_worktree(git_repo, "nope", fleet_home / "worktrees" / "x")


def test_has_uncommitted_changes_tracks_real_git_state(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.email=t@t",
            "-c",
            "user.name=t",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "base",
        ],
        check=True,
    )
    assert has_uncommitted_changes(repo) is False
    (repo / "new.txt").write_text("x")
    assert has_uncommitted_changes(repo) is True
    # Unknown state (not a repo) counts as dirty so work is never discarded.
    assert has_uncommitted_changes(tmp_path / "nowhere") is True
