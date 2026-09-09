"""Tests for orchestrator/merge_validation.py (moved from test_validation.py)."""

from __future__ import annotations

import asyncio
import inspect
import json
import subprocess
from pathlib import Path

from fleet.core.config import RuntimeConfig
from fleet.core.limits import CLAIM_POLL_INTERVAL_SEC
from fleet.core.task import Task
from fleet.orchestrator import merge_validation as mv_mod
from fleet.orchestrator import worktree
from fleet.orchestrator.merge_validation import MergeValidation
from fleet.orchestrator.service import ServiceOrder
from tests.conftest import make_running_worker, make_supervisor


class StubCoder:
    name = "stub"

    def build_argv(self, task, task_dir, plan=None):
        return ["echo"]

    def env(self, task, artifact_dir):
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

    def claim_next(self, claimer_id, *, can_claim=None):
        return None

    def release(self, task_id, reason="", wait_sec=0):
        self.released.append((task_id, reason))

    def set_blocked(self, task_id, reason):
        self.blocked.append((task_id, reason))

    def close(self, task_id, reason="completed"):
        self.closed.append((task_id, reason))

    def comment(self, task_id, body):
        self.comments.append((task_id, body))

    def get(self, task_id):

        return Task(id=task_id, title="T", description=None, status=self._status)

    def list_ready(self, limit=50):
        return []

    def clear_isolation_info(self, task_id):
        pass


def _make_state(tmp_path: Path, queue: StubQueue, config: RuntimeConfig | None = None):
    sup = make_supervisor(tmp_path, queue=queue, services=[], checks=[])
    sup.state.fleet_home = tmp_path / ".fleet"
    if config is not None:
        sup.state.config = config
    return sup.state


def _git(path: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(path), *args], capture_output=True, check=True)


def _git_init(path: Path) -> None:
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


def _isolate(
    fleet_home: Path, repo: Path, task_id: str, base_ref: str = "main"
) -> tuple[Path, Path]:
    """Create task.json isolation info + .needs_validation; return (task_dir, wt)."""
    task_dir = fleet_home / "tasks" / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / ".needs_validation").write_text("1")
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


def _setup_repo(tmp_path: Path) -> tuple[Path, Path]:
    fleet_home = tmp_path / ".fleet"
    fleet_home.mkdir(exist_ok=True)
    repo = tmp_path / "repo"
    repo.mkdir(exist_ok=True)
    if not (repo / ".git").exists():
        _git_init(repo)
    return fleet_home, repo


def _run(st) -> None:
    asyncio.run(MergeValidation().tick(st))


def test_order_and_default_interval() -> None:
    assert MergeValidation.order == ServiceOrder.Claim
    assert MergeValidation().interval_sec == CLAIM_POLL_INTERVAL_SEC
    assert MergeValidation(interval_sec=0.01).interval_sec == 0.01


# ===== CLEAN MERGE =====


class TestCleanMerge:
    def test_close_called_with_validated_reason(self, tmp_path: Path):
        fleet_home, repo = _setup_repo(tmp_path)
        task_id = "test-val-1"
        _, wt = _isolate(fleet_home, repo, task_id)
        _commit(wt, "feature.txt", "feature content")

        queue = StubQueue(status="in_progress")
        st = _make_state(tmp_path, queue)
        _run(st)

        assert len(queue.closed) == 1
        assert queue.closed[0][0] == task_id
        assert "validated" in queue.closed[0][1]
        assert (repo / "feature.txt").read_text() == "feature content"

    def test_needs_validation_cleared_on_success(self, tmp_path: Path):
        fleet_home, repo = _setup_repo(tmp_path)
        task_id = "test-val-2"
        task_dir, wt = _isolate(fleet_home, repo, task_id)
        _commit(wt, "feature2.txt", "feature2")

        queue = StubQueue(status="in_progress")
        st = _make_state(tmp_path, queue)
        _run(st)

        assert not (task_dir / ".needs_validation").exists()

    def test_worktree_removed_on_success(self, tmp_path: Path):
        fleet_home, repo = _setup_repo(tmp_path)
        task_id = "test-val-3"
        _, wt = _isolate(fleet_home, repo, task_id)
        _commit(wt, "feat3.txt", "f3")

        queue = StubQueue(status="in_progress")
        st = _make_state(tmp_path, queue)
        _run(st)

        assert not wt.exists()


# ===== CONFLICT =====


class TestConflict:
    def _setup_conflict(self, fleet_home: Path, repo: Path, task_id: str) -> tuple[Path, Path]:
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

    def test_set_blocked_not_close_on_conflict(self, tmp_path: Path):
        fleet_home, repo = _setup_repo(tmp_path)
        task_id = "test-conflict-1"
        self._setup_conflict(fleet_home, repo, task_id)

        queue = StubQueue(status="in_progress")
        st = _make_state(tmp_path, queue)
        _run(st)

        assert queue.closed == []
        assert len(queue.blocked) == 1
        assert queue.blocked[0][0] == task_id
        assert "merge conflict" in queue.blocked[0][1]

    def test_needs_validation_cleared_on_conflict(self, tmp_path: Path):
        fleet_home, repo = _setup_repo(tmp_path)
        task_id = "test-conflict-2"
        task_dir, _ = self._setup_conflict(fleet_home, repo, task_id)

        queue = StubQueue(status="in_progress")
        st = _make_state(tmp_path, queue)
        _run(st)

        assert not (task_dir / ".needs_validation").exists()

    def test_main_tree_clean_after_conflict(self, tmp_path: Path):
        fleet_home, repo = _setup_repo(tmp_path)
        task_id = "test-conflict-3"
        self._setup_conflict(fleet_home, repo, task_id)

        queue = StubQueue(status="in_progress")
        st = _make_state(tmp_path, queue)
        _run(st)

        status = subprocess.run(
            ["git", "-C", str(repo), "status", "--porcelain", "--untracked-files=no"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert status.stdout.strip() == ""


class TestDirtyBase:
    def test_dirty_base_blocks_without_touching(self, tmp_path: Path):
        fleet_home, repo = _setup_repo(tmp_path)
        task_id = "test-dirty-1"
        _, wt = _isolate(fleet_home, repo, task_id)
        _commit(wt, "f.txt", "work")
        (repo / "uncommitted.txt").write_text("x")
        _git(repo, "add", "uncommitted.txt")
        (repo / "uncommitted.txt").write_text("modified")
        head_before = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()

        queue = StubQueue(status="in_progress")
        st = _make_state(tmp_path, queue)
        _run(st)

        assert queue.closed == []
        assert len(queue.blocked) == 1
        assert "base repo dirty" in queue.blocked[0][1]
        head_after = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
        assert head_before == head_after


class TestPostMergeCommand:
    def test_post_merge_failure_blocks_with_tail(self, tmp_path: Path):
        fleet_home, repo = _setup_repo(tmp_path)
        task_id = "test-post-1"
        _, wt = _isolate(fleet_home, repo, task_id)
        _commit(wt, "f.txt", "work")

        queue = StubQueue(status="in_progress")
        cfg = RuntimeConfig(
            post_merge_command="python3 -c 'import sys; print(\"gate-boom\"); sys.exit(1)'"
        )
        st = _make_state(tmp_path, queue, config=cfg)
        _run(st)

        assert queue.closed == []
        assert len(queue.blocked) == 1
        assert "gate-boom" in queue.blocked[0][1]

    def test_post_merge_empty_skips(self, tmp_path: Path):
        fleet_home, repo = _setup_repo(tmp_path)
        task_id = "test-post-2"
        _, wt = _isolate(fleet_home, repo, task_id)
        _commit(wt, "f.txt", "work")

        queue = StubQueue(status="in_progress")
        st = _make_state(tmp_path, queue, config=RuntimeConfig(post_merge_command=""))
        _run(st)

        assert len(queue.closed) == 1

    def test_command_runs_and_closes_on_success(self, tmp_path: Path):
        fleet_home, repo = _setup_repo(tmp_path)
        task_id = "test-pm-1"
        _, wt = _isolate(fleet_home, repo, task_id)
        _commit(wt, "f.txt", "work")

        queue = StubQueue(status="in_progress")
        cfg = RuntimeConfig(post_merge_command="python3 -c 'import sys; sys.exit(0)'")
        st = _make_state(tmp_path, queue, config=cfg)
        _run(st)

        assert len(queue.closed) == 1

    def test_empty_command_skips_without_subprocess(self, tmp_path: Path, monkeypatch):
        fleet_home, repo = _setup_repo(tmp_path)
        task_id = "test-pm-2"
        _, wt = _isolate(fleet_home, repo, task_id)
        _commit(wt, "f.txt", "work")

        queue = StubQueue(status="in_progress")
        st = _make_state(tmp_path, queue, config=RuntimeConfig(post_merge_command=""))
        called = []
        orig = worktree.run_post_merge_command
        monkeypatch.setattr(
            worktree, "run_post_merge_command", lambda *a, **k: (called.append(1), orig(*a, **k))[1]
        )
        _run(st)
        assert len(queue.closed) == 1
        assert called == []

    def test_failure_blocks_with_tail(self, tmp_path: Path):
        fleet_home, repo = _setup_repo(tmp_path)
        task_id = "test-pm-3"
        _, wt = _isolate(fleet_home, repo, task_id)
        _commit(wt, "f.txt", "work")

        queue = StubQueue(status="in_progress")
        cfg = RuntimeConfig(
            post_merge_command="python3 -c 'import sys; print(\"gate-tail-marker\"); sys.exit(2)'"
        )
        st = _make_state(tmp_path, queue, config=cfg)
        _run(st)

        assert queue.closed == []
        assert len(queue.blocked) == 1
        assert "gate-tail-marker" in queue.blocked[0][1]

    def test_no_ui_prefix_special_case(self, tmp_path: Path):
        """Any file type merges the same; no src/fleet/ui diff special-casing remains."""

        src = inspect.getsource(mv_mod)
        assert "src/fleet/ui" not in src
        assert "create_subprocess_exec" not in src
        assert "post_merge_command" in src


# ===== IN-FLIGHT SKIP =====


class TestInFlightSkip:
    def test_running_task_skipped(self, tmp_path: Path):
        fleet_home, repo = _setup_repo(tmp_path)
        task_id = "test-inflight-1"
        task_dir, wt = _isolate(fleet_home, repo, task_id)
        _commit(wt, "feature_inflight.txt", "inflight")

        queue = StubQueue(status="in_progress")
        st = _make_state(tmp_path, queue)
        st.running[task_id] = make_running_worker(task_id, tmp_path)
        _run(st)

        assert queue.closed == []
        assert queue.blocked == []
        assert (task_dir / ".needs_validation").exists()
