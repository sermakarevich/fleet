from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest
from fleet.orchestrator.supervisor import Supervisor


class StubCoder:
    name = "stub"

    def build_argv(self, task, task_dir):
        return ["echo"]

    def env(self, task, task_dir):
        return {}

    def normalize_event(self, raw_line):
        return None


class StubQueue:
    def __init__(self, status: str = "open") -> None:
        self._status = status
        self.released: list[tuple[str, str]] = []
        self.closed: list[tuple[str, str]] = []
        self.blocked: list[tuple[str, str]] = []
        self.comments: list[tuple[str, str]] = []

    def claim_next(self, claimer_id):
        return None

    def release(self, task_id, reason=""):
        self.released.append((task_id, reason))

    def set_blocked(self, task_id, reason):
        self.blocked.append((task_id, reason))

    def close(self, task_id, reason="completed"):
        self.closed.append((task_id, reason))

    def comment(self, task_id, body):
        self.comments.append((task_id, body))

    def get(self, task_id):
        from fleet.core.task import Task

        return Task(id=task_id, title="T", description=None, status=self._status)

    def list_ready(self, limit=50):
        return []


def _make_supervisor(tmp_path: Path, queue: StubQueue) -> Supervisor:
    s = Supervisor(
        coder=StubCoder(),
        queue=queue,
        runtime_toml_path=tmp_path / "runtime.toml",
        project_root=tmp_path,
        log=__import__("structlog").get_logger(),
    )
    return s


def _git_init(path: Path) -> None:
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


def _create_task_dir(tmp_path: Path, task_id: str) -> Path:
    task_dir = tmp_path / "tasks" / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    return task_dir


# ===== CLEAN MERGE =====


class TestCleanMerge:
    def test_close_called_with_validated_reason(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """CLEAN MERGE: close() called with that id."""
        monkeypatch.setenv("FLEET_HOME", str(tmp_path / ".fleet"))
        monkeypatch.setenv("FLEET_WORKTREE_ISOLATION", "1")
        _git_init(tmp_path)

        task_id = "test-val-1"
        task_dir = _create_task_dir(tmp_path, task_id)
        (task_dir / ".needs_validation").write_text("1")
        worktree_dir = tmp_path / ".fleet" / "worktrees" / task_id
        worktree_dir.mkdir(parents=True, exist_ok=True)

        branch = f"fleet/{task_id}"
        subprocess.run(
            ["git", "-C", str(tmp_path), "checkout", "-b", branch],
            capture_output=True,
            check=True,
        )
        feature_file = tmp_path / "feature.txt"
        feature_file.write_text("feature content")
        subprocess.run(
            [
                "git",
                "-C",
                str(tmp_path),
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
                str(tmp_path),
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
        subprocess.run(
            ["git", "-C", str(tmp_path), "checkout", "main"],
            capture_output=True,
            check=True,
        )

        queue = StubQueue(status="in_progress")
        s = _make_supervisor(tmp_path, queue)
        asyncio.run(s._run_pending_validations())

        assert len(queue.closed) == 1
        assert queue.closed[0][0] == task_id
        assert "validated" in queue.closed[0][1]
        assert feature_file.exists()
        assert feature_file.read_text() == "feature content"

    def test_needs_validation_cleared_on_success(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """CLEAN MERGE: .needs_validation cleared after success."""
        monkeypatch.setenv("FLEET_HOME", str(tmp_path / ".fleet"))
        monkeypatch.setenv("FLEET_WORKTREE_ISOLATION", "1")
        _git_init(tmp_path)

        task_id = "test-val-2"
        task_dir = _create_task_dir(tmp_path, task_id)
        (task_dir / ".needs_validation").write_text("1")

        branch = f"fleet/{task_id}"
        subprocess.run(
            ["git", "-C", str(tmp_path), "checkout", "-b", branch],
            capture_output=True,
            check=True,
        )
        (tmp_path / "feature2.txt").write_text("feature2")
        subprocess.run(
            [
                "git",
                "-C",
                str(tmp_path),
                "-c",
                "user.email=test@test.com",
                "-c",
                "user.name=test",
                "add",
                "feature2.txt",
            ],
            capture_output=True,
            check=True,
        )
        subprocess.run(
            [
                "git",
                "-C",
                str(tmp_path),
                "-c",
                "user.email=test@test.com",
                "-c",
                "user.name=test",
                "commit",
                "-m",
                "add feature2",
            ],
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(tmp_path), "checkout", "main"],
            capture_output=True,
            check=True,
        )

        queue = StubQueue(status="in_progress")
        s = _make_supervisor(tmp_path, queue)
        asyncio.run(s._run_pending_validations())

        assert not (task_dir / ".needs_validation").exists()

    def test_worktree_marker_removed_on_success(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """CLEAN MERGE: .worktree marker removed after success."""
        monkeypatch.setenv("FLEET_HOME", str(tmp_path / ".fleet"))
        monkeypatch.setenv("FLEET_WORKTREE_ISOLATION", "1")
        _git_init(tmp_path)

        task_id = "test-val-3"
        task_dir = _create_task_dir(tmp_path, task_id)
        (task_dir / ".needs_validation").write_text("1")
        (task_dir / ".worktree").write_text(
            str(tmp_path / ".fleet" / "worktrees" / task_id)
        )

        branch = f"fleet/{task_id}"
        subprocess.run(
            ["git", "-C", str(tmp_path), "checkout", "-b", branch],
            capture_output=True,
            check=True,
        )
        (tmp_path / "feat3.txt").write_text("f3")
        subprocess.run(
            [
                "git",
                "-C",
                str(tmp_path),
                "-c",
                "user.email=test@test.com",
                "-c",
                "user.name=test",
                "add",
                "feat3.txt",
            ],
            capture_output=True,
            check=True,
        )
        subprocess.run(
            [
                "git",
                "-C",
                str(tmp_path),
                "-c",
                "user.email=test@test.com",
                "-c",
                "user.name=test",
                "commit",
                "-m",
                "feat3",
            ],
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(tmp_path), "checkout", "main"],
            capture_output=True,
            check=True,
        )

        queue = StubQueue(status="in_progress")
        s = _make_supervisor(tmp_path, queue)
        asyncio.run(s._run_pending_validations())

        assert not (task_dir / ".worktree").exists()


# ===== CONFLICT =====


class TestConflict:
    def _setup_conflict_repo(self, tmp_path: Path):
        """Set up a repo with a tracked file committed on both main and a branch."""
        _git_init(tmp_path)
        tracked = tmp_path / "tracked.txt"
        tracked.write_text("line1\nline2\n")
        subprocess.run(
            [
                "git",
                "-C",
                str(tmp_path),
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
                str(tmp_path),
                "-c",
                "user.email=test@test.com",
                "-c",
                "user.name=test",
                "commit",
                "-m",
                "initial",
            ],
            capture_output=True,
            check=True,
        )

    def test_set_blocked_not_close_on_conflict(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """CONFLICT: set_blocked called (not close)."""
        monkeypatch.setenv("FLEET_HOME", str(tmp_path / ".fleet"))
        monkeypatch.setenv("FLEET_WORKTREE_ISOLATION", "1")
        self._setup_conflict_repo(tmp_path)

        task_id = "test-conflict-1"
        task_dir = _create_task_dir(tmp_path, task_id)
        (task_dir / ".needs_validation").write_text("1")

        branch = f"fleet/{task_id}"
        subprocess.run(
            ["git", "-C", str(tmp_path), "checkout", "-b", branch],
            capture_output=True,
            check=True,
        )
        tracked = tmp_path / "tracked.txt"
        tracked.write_text("branch version\nline2\n")
        subprocess.run(
            [
                "git",
                "-C",
                str(tmp_path),
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
                str(tmp_path),
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
        subprocess.run(
            ["git", "-C", str(tmp_path), "checkout", "main"],
            capture_output=True,
            check=True,
        )
        tracked.write_text("main version\nline2\n")
        subprocess.run(
            [
                "git",
                "-C",
                str(tmp_path),
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
                str(tmp_path),
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

        queue = StubQueue(status="in_progress")
        s = _make_supervisor(tmp_path, queue)
        asyncio.run(s._run_pending_validations())

        assert queue.closed == []
        assert len(queue.blocked) == 1
        assert queue.blocked[0][0] == task_id
        assert "merge conflict" in queue.blocked[0][1]

    def test_needs_validation_cleared_on_conflict(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """CONFLICT: marker cleared even on conflict."""
        monkeypatch.setenv("FLEET_HOME", str(tmp_path / ".fleet"))
        monkeypatch.setenv("FLEET_WORKTREE_ISOLATION", "1")
        self._setup_conflict_repo(tmp_path)

        task_id = "test-conflict-2"
        task_dir = _create_task_dir(tmp_path, task_id)
        (task_dir / ".needs_validation").write_text("1")

        branch = f"fleet/{task_id}"
        subprocess.run(
            ["git", "-C", str(tmp_path), "checkout", "-b", branch],
            capture_output=True,
            check=True,
        )
        tracked = tmp_path / "tracked.txt"
        tracked.write_text("branch\n")
        subprocess.run(
            [
                "git",
                "-C",
                str(tmp_path),
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
                str(tmp_path),
                "-c",
                "user.email=test@test.com",
                "-c",
                "user.name=test",
                "commit",
                "-m",
                "edit branch",
            ],
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(tmp_path), "checkout", "main"],
            capture_output=True,
            check=True,
        )
        tracked.write_text("main\n")
        subprocess.run(
            [
                "git",
                "-C",
                str(tmp_path),
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
                str(tmp_path),
                "-c",
                "user.email=test@test.com",
                "-c",
                "user.name=test",
                "commit",
                "-m",
                "edit main",
            ],
            capture_output=True,
            check=True,
        )

        queue = StubQueue(status="in_progress")
        s = _make_supervisor(tmp_path, queue)
        asyncio.run(s._run_pending_validations())

        assert not (task_dir / ".needs_validation").exists()

    def test_main_tree_clean_after_conflict(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """CONFLICT: main tree is clean (merge aborted)."""
        monkeypatch.setenv("FLEET_HOME", str(tmp_path / ".fleet"))
        monkeypatch.setenv("FLEET_WORKTREE_ISOLATION", "1")
        self._setup_conflict_repo(tmp_path)

        task_id = "test-conflict-3"
        task_dir = _create_task_dir(tmp_path, task_id)
        (task_dir / ".needs_validation").write_text("1")

        branch = f"fleet/{task_id}"
        subprocess.run(
            ["git", "-C", str(tmp_path), "checkout", "-b", branch],
            capture_output=True,
            check=True,
        )
        tracked = tmp_path / "tracked.txt"
        tracked.write_text("branch\n")
        subprocess.run(
            [
                "git",
                "-C",
                str(tmp_path),
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
                str(tmp_path),
                "-c",
                "user.email=test@test.com",
                "-c",
                "user.name=test",
                "commit",
                "-m",
                "edit branch",
            ],
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(tmp_path), "checkout", "main"],
            capture_output=True,
            check=True,
        )
        tracked.write_text("main\n")
        subprocess.run(
            [
                "git",
                "-C",
                str(tmp_path),
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
                str(tmp_path),
                "-c",
                "user.email=test@test.com",
                "-c",
                "user.name=test",
                "commit",
                "-m",
                "edit main",
            ],
            capture_output=True,
            check=True,
        )

        queue = StubQueue(status="in_progress")
        s = _make_supervisor(tmp_path, queue)
        asyncio.run(s._run_pending_validations())

        status = subprocess.run(
            [
                "git",
                "-C",
                str(tmp_path),
                "status",
                "--porcelain",
                "--untracked-files=no",
            ],
            capture_output=True,
            text=True,
        )
        assert status.stdout.strip() == ""
        head = subprocess.run(
            ["git", "-C", str(tmp_path), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
        ).stdout.strip()
        assert head == "main"


# ===== IN-FLIGHT SKIP =====


class TestInFlightSkip:
    def test_in_flight_task_skipped(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """Task in self.in_flight => skipped (no merge attempted)."""
        monkeypatch.setenv("FLEET_HOME", str(tmp_path / ".fleet"))
        monkeypatch.setenv("FLEET_WORKTREE_ISOLATION", "1")
        _git_init(tmp_path)

        task_id = "test-inflight-1"
        task_dir = _create_task_dir(tmp_path, task_id)
        (task_dir / ".needs_validation").write_text("1")

        branch = f"fleet/{task_id}"
        subprocess.run(
            ["git", "-C", str(tmp_path), "checkout", "-b", branch],
            capture_output=True,
            check=True,
        )
        (tmp_path / "feature_inflight.txt").write_text("inflight")
        subprocess.run(
            [
                "git",
                "-C",
                str(tmp_path),
                "-c",
                "user.email=test@test.com",
                "-c",
                "user.name=test",
                "add",
                "feature_inflight.txt",
            ],
            capture_output=True,
            check=True,
        )
        subprocess.run(
            [
                "git",
                "-C",
                str(tmp_path),
                "-c",
                "user.email=test@test.com",
                "-c",
                "user.name=test",
                "commit",
                "-m",
                "feature_inflight",
            ],
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(tmp_path), "checkout", "main"],
            capture_output=True,
            check=True,
        )

        queue = StubQueue(status="in_progress")
        s = _make_supervisor(tmp_path, queue)

        # Use asyncio.sleep to create a valid Task
        async def _make_task():
            await asyncio.sleep(0)
            return "done"

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            s.in_flight[task_id] = loop.create_task(_make_task())
        finally:
            loop.close()

        asyncio.run(s._run_pending_validations())

        asyncio.run(s._run_pending_validations())

        assert queue.closed == []
        assert queue.blocked == []
        assert (task_dir / ".needs_validation").exists()
