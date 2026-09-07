from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from unittest import mock

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


def _setup_clean_merge(tmp_path: Path, task_id: str) -> None:
    """Helper: set up a repo, create a branch with a commit, return to main."""
    branch = f"fleet/{task_id}"
    subprocess.run(
        ["git", "-C", str(tmp_path), "checkout", "-b", branch],
        capture_output=True,
        check=True,
    )
    (tmp_path / "feature.txt").write_text("feature content")
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


class _GrepResult:
    """Thin wrapper to make .stdout return an actual string (not a Mock)."""

    def __init__(self, out: str):
        self.stdout = out


def _make_subprocess_side_effect(ui_diff_output: str):
    """Return a side_effect function for subprocess.run that:
    - returns our git diff mock for 'git diff' calls
    - returns a successful result for all other calls (e.g. worktree remove)
    """

    def side_effect(*args, **kwargs):
        # supervisor passes list as first positional arg: [git, -C, path, diff, ...]
        cmd = args[0] if args else []
        # Our code: git -C <path> diff --name-only HEAD~1 HEAD
        if len(cmd) >= 5 and cmd[0] == "git" and cmd[3] == "diff":
            return _GrepResult(ui_diff_output)
        # Everything else (worktree removal, etc.)
        result = mock.Mock()
        result.returncode = 0
        result.stderr = ""
        return result

    return side_effect


# ===== UI rebuild triggered when UI files changed =====


class TestUiRebuildOnUiChange:
    def test_make_ui_build_invoked_when_ui_file_in_diff(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """UI file in merge diff => make ui-build is called."""
        monkeypatch.setenv("FLEET_HOME", str(tmp_path / ".fleet"))
        monkeypatch.setenv("FLEET_WORKTREE_ISOLATION", "1")
        _git_init(tmp_path)

        task_id = "test-ui-1"
        task_dir = _create_task_dir(tmp_path, task_id)
        (task_dir / ".needs_validation").write_text("1")
        worktree_dir = tmp_path / ".fleet" / "worktrees" / task_id
        worktree_dir.mkdir(parents=True, exist_ok=True)

        _setup_clean_merge(tmp_path, task_id)

        queue = StubQueue(status="in_progress")
        s = _make_supervisor(tmp_path, queue)

        ui_files = "src/fleet/ui/components/Dashboard.tsx"

        mock_proc = mock.AsyncMock()
        mock_proc.wait = mock.AsyncMock(return_value=0)

        called_with = []

        async def fake_create_subprocess_exec(*args, **kwargs):
            called_with.append((args, kwargs))
            return mock_proc

        monkeypatch.setattr(
            "fleet.orchestrator.claim.subprocess.run", _make_subprocess_side_effect(ui_files)
        )
        monkeypatch.setattr(
            "asyncio.create_subprocess_exec", fake_create_subprocess_exec
        )

        asyncio.run(s._run_pending_validations())

        assert len(called_with) == 1
        assert called_with[0][0][0] == "make"
        assert called_with[0][0][1] == "ui-build"
        assert len(queue.closed) == 1

    def test_make_ui_build_not_invoked_when_only_backend_files_changed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """Only backend files in merge diff => make ui-build NOT called."""
        monkeypatch.setenv("FLEET_HOME", str(tmp_path / ".fleet"))
        monkeypatch.setenv("FLEET_WORKTREE_ISOLATION", "1")
        _git_init(tmp_path)

        task_id = "test-ui-2"
        task_dir = _create_task_dir(tmp_path, task_id)
        (task_dir / ".needs_validation").write_text("1")
        worktree_dir = tmp_path / ".fleet" / "worktrees" / task_id
        worktree_dir.mkdir(parents=True, exist_ok=True)

        _setup_clean_merge(tmp_path, task_id)

        queue = StubQueue(status="in_progress")
        s = _make_supervisor(tmp_path, queue)

        backend_files = "src/fleet/coders/base.py\nsrc/fleet/schemas.py\n"
        called_with = []

        async def fake_create_subprocess_exec(*args, **kwargs):
            called_with.append((args, kwargs))
            mock_proc = mock.AsyncMock()
            mock_proc.wait = mock.AsyncMock(return_value=0)
            return mock_proc

        monkeypatch.setattr(
            "fleet.orchestrator.claim.subprocess.run",
            _make_subprocess_side_effect(backend_files),
        )
        monkeypatch.setattr(
            "asyncio.create_subprocess_exec", fake_create_subprocess_exec
        )

        asyncio.run(s._run_pending_validations())

        assert queue.closed == [
            (task_id, "validated: merged fleet/test-ui-2 into main")
        ]
        assert len(called_with) == 0


# ===== UI rebuild success/failure logging =====


class TestUiRebuildLogging:
    def test_ui_rebuild_success_logs_info(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """Successful build returns rc=0 and logs ui.rebuilt."""
        monkeypatch.setenv("FLEET_HOME", str(tmp_path / ".fleet"))
        monkeypatch.setenv("FLEET_WORKTREE_ISOLATION", "1")
        _git_init(tmp_path)

        task_id = "test-ui-3"
        task_dir = _create_task_dir(tmp_path, task_id)
        (task_dir / ".needs_validation").write_text("1")
        worktree_dir = tmp_path / ".fleet" / "worktrees" / task_id
        worktree_dir.mkdir(parents=True, exist_ok=True)

        _setup_clean_merge(tmp_path, task_id)

        queue = StubQueue(status="in_progress")
        log_logger = mock.MagicMock()
        s = _make_supervisor(tmp_path, queue)
        s._log = log_logger

        mock_proc = mock.AsyncMock()
        mock_proc.wait = mock.AsyncMock(return_value=0)

        async def fake_create_subprocess_exec(*args, **kwargs):
            return mock_proc

        monkeypatch.setattr(
            "fleet.orchestrator.claim.subprocess.run",
            _make_subprocess_side_effect("src/fleet/ui/app.tsx"),
        )
        monkeypatch.setattr(
            "asyncio.create_subprocess_exec", fake_create_subprocess_exec
        )

        asyncio.run(s._run_pending_validations())

        call_args = log_logger.info.call_args_list
        rebuild_logs = [c for c in call_args if c.args[0] == "ui.rebuilt"]
        assert len(rebuild_logs) == 1

    def test_ui_rebuild_failure_logs_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """Failed build returns rc!=0 and logs ui.rebuild_failed."""
        monkeypatch.setenv("FLEET_HOME", str(tmp_path / ".fleet"))
        monkeypatch.setenv("FLEET_WORKTREE_ISOLATION", "1")
        _git_init(tmp_path)

        task_id = "test-ui-4"
        task_dir = _create_task_dir(tmp_path, task_id)
        (task_dir / ".needs_validation").write_text("1")
        worktree_dir = tmp_path / ".fleet" / "worktrees" / task_id
        worktree_dir.mkdir(parents=True, exist_ok=True)

        _setup_clean_merge(tmp_path, task_id)

        queue = StubQueue(status="in_progress")
        log_logger = mock.MagicMock()
        s = _make_supervisor(tmp_path, queue)
        s._log = log_logger

        mock_proc = mock.AsyncMock()
        mock_proc.wait = mock.AsyncMock(return_value=1)

        async def fake_create_subprocess_exec(*args, **kwargs):
            return mock_proc

        monkeypatch.setattr(
            "fleet.orchestrator.claim.subprocess.run",
            _make_subprocess_side_effect("src/fleet/ui/app.tsx"),
        )
        monkeypatch.setattr(
            "asyncio.create_subprocess_exec", fake_create_subprocess_exec
        )

        asyncio.run(s._run_pending_validations())

        call_args = log_logger.error.call_args_list
        rebuild_logs = [c for c in call_args if c.args[0] == "ui.rebuild_failed"]
        assert len(rebuild_logs) == 1

    def test_ui_rebuild_success_with_mixed_paths_includes_ui(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """Diff contains both backend and UI files => build invoked."""
        monkeypatch.setenv("FLEET_HOME", str(tmp_path / ".fleet"))
        monkeypatch.setenv("FLEET_WORKTREE_ISOLATION", "1")
        _git_init(tmp_path)

        task_id = "test-ui-5"
        task_dir = _create_task_dir(tmp_path, task_id)
        (task_dir / ".needs_validation").write_text("1")
        worktree_dir = tmp_path / ".fleet" / "worktrees" / task_id
        worktree_dir.mkdir(parents=True, exist_ok=True)

        _setup_clean_merge(tmp_path, task_id)

        queue = StubQueue(status="in_progress")
        s = _make_supervisor(tmp_path, queue)

        mixed_files = (
            "src/fleet/coders/base.py\nsrc/fleet/ui/app.tsx\nfleet/schemas.py\n"
        )
        called_with = []

        mock_proc = mock.AsyncMock()
        mock_proc.wait = mock.AsyncMock(return_value=0)

        async def fake_create_subprocess_exec(*args, **kwargs):
            called_with.append((args, kwargs))
            mock_proc = mock.AsyncMock()
            mock_proc.wait = mock.AsyncMock(return_value=0)
            return mock_proc

        monkeypatch.setattr(
            "fleet.orchestrator.claim.subprocess.run", _make_subprocess_side_effect(mixed_files)
        )
        monkeypatch.setattr(
            "asyncio.create_subprocess_exec", fake_create_subprocess_exec
        )

        asyncio.run(s._run_pending_validations())

        assert len(called_with) == 1
        assert called_with[0][0][0] == "make"
        assert called_with[0][0][1] == "ui-build"

    def test_ui_rebuild_empty_diff_no_build(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """Empty diff (e.g., rename-only merge) => no build."""
        monkeypatch.setenv("FLEET_HOME", str(tmp_path / ".fleet"))
        monkeypatch.setenv("FLEET_WORKTREE_ISOLATION", "1")
        _git_init(tmp_path)

        task_id = "test-ui-6"
        task_dir = _create_task_dir(tmp_path, task_id)
        (task_dir / ".needs_validation").write_text("1")
        worktree_dir = tmp_path / ".fleet" / "worktrees" / task_id
        worktree_dir.mkdir(parents=True, exist_ok=True)

        _setup_clean_merge(tmp_path, task_id)

        queue = StubQueue(status="in_progress")
        s = _make_supervisor(tmp_path, queue)

        called_with = []

        async def fake_create_subprocess_exec(*args, **kwargs):
            called_with.append((args, kwargs))
            mock_proc = mock.AsyncMock()
            mock_proc.wait = mock.AsyncMock(return_value=0)
            return mock_proc

        monkeypatch.setattr("subprocess.run", _make_subprocess_side_effect(""))
        monkeypatch.setattr(
            "asyncio.create_subprocess_exec", fake_create_subprocess_exec
        )

        asyncio.run(s._run_pending_validations())

        assert queue.closed == [
            (task_id, "validated: merged fleet/test-ui-6 into main")
        ]
        assert len(called_with) == 0
