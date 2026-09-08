"""Post-merge command: config-driven validation step (replaces hardcoded ui-build)."""

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path

from fleet.core.config import RuntimeConfig
from fleet.orchestrator import worktree
from fleet.orchestrator.supervisor import Supervisor


class StubCoder:
    name = "stub"

    def build_argv(self, task, task_dir, plan=None):
        return ["echo"]

    def env(self, task, task_dir):
        return {}

    def normalize_event(self, raw_line):
        return None


class StubQueue:
    def __init__(self, status: str = "open") -> None:
        self._status = status
        self.closed: list[tuple[str, str]] = []
        self.blocked: list[tuple[str, str]] = []

    def claim_next(self, claimer_id):
        return None

    def release(self, task_id, reason="", wait_sec=0):
        pass

    def set_blocked(self, task_id, reason):
        self.blocked.append((task_id, reason))

    def close(self, task_id, reason="completed"):
        self.closed.append((task_id, reason))

    def comment(self, task_id, body):
        pass

    def get(self, task_id):
        from fleet.core.task import Task

        return Task(id=task_id, title="T", description=None, status=self._status)

    def list_ready(self, limit=50):
        return []

    def clear_isolation_info(self, task_id):
        pass


def _make_supervisor(
    tmp_path: Path, queue: StubQueue, config: RuntimeConfig | None = None
) -> Supervisor:
    s = Supervisor(
        coder=StubCoder(),
        queue=queue,
        runtime_toml_path=tmp_path / "runtime.toml",
        project_root=tmp_path / ".fleet",
        log=__import__("structlog").get_logger(),
    )
    s.config = config or RuntimeConfig()
    return s


def _git_init(path: Path) -> None:
    subprocess.run(["git", "init", "-b", "main"], cwd=path, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "t@t.com"], cwd=path, capture_output=True
    )
    subprocess.run(["git", "config", "user.name", "t"], cwd=path, capture_output=True)
    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", "init"],
        cwd=path,
        capture_output=True,
        check=True,
    )


def _setup(tmp_path: Path, task_id: str) -> Path:
    fleet_home = tmp_path / ".fleet"
    fleet_home.mkdir(exist_ok=True)
    repo = tmp_path / "repo"
    if not (repo / ".git").exists():
        repo.mkdir(exist_ok=True)
        _git_init(repo)
    task_dir = fleet_home / "tasks" / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / ".needs_validation").write_text("1")
    wt = worktree.create_worktree(repo, task_id, base_ref="main", fleet_home=fleet_home)
    (wt / "feature.txt").write_text("feature")
    subprocess.run(["git", "-C", str(wt), "add", "feature.txt"], capture_output=True, check=True)
    subprocess.run(
        [
            "git", "-C", str(wt), "-c", "user.email=t@t.com", "-c", "user.name=t",
            "commit", "-m", "feat",
        ],
        capture_output=True,
        check=True,
    )
    (task_dir / "task.json").write_text(
        json.dumps(
            {
                "id": task_id,
                "repo_root": str(repo),
                "base_ref": "main",
                "worktree_path": str(wt),
            }
        )
    )
    return task_dir


class TestPostMergeCommand:
    def test_command_runs_and_closes_on_success(self, tmp_path: Path):
        task_id = "test-pm-1"
        _setup(tmp_path, task_id)
        queue = StubQueue(status="in_progress")
        cfg = RuntimeConfig(post_merge_command="python3 -c 'import sys; sys.exit(0)'")
        s = _make_supervisor(tmp_path, queue, config=cfg)
        asyncio.run(s._run_pending_validations())
        assert len(queue.closed) == 1

    def test_empty_command_skips_without_subprocess(self, tmp_path: Path, monkeypatch):
        task_id = "test-pm-2"
        _setup(tmp_path, task_id)
        queue = StubQueue(status="in_progress")
        s = _make_supervisor(tmp_path, queue, config=RuntimeConfig(post_merge_command=""))
        called = []
        orig = worktree.run_post_merge_command
        monkeypatch.setattr(
            worktree, "run_post_merge_command", lambda *a, **k: (called.append(1), orig(*a, **k))[1]
        )
        asyncio.run(s._run_pending_validations())
        assert len(queue.closed) == 1
        assert called == []

    def test_failure_blocks_with_tail(self, tmp_path: Path):
        task_id = "test-pm-3"
        _setup(tmp_path, task_id)
        queue = StubQueue(status="in_progress")
        cfg = RuntimeConfig(
            post_merge_command="python3 -c 'import sys; print(\"gate-tail-marker\"); sys.exit(2)'"
        )
        s = _make_supervisor(tmp_path, queue, config=cfg)
        asyncio.run(s._run_pending_validations())
        assert queue.closed == []
        assert len(queue.blocked) == 1
        assert "gate-tail-marker" in queue.blocked[0][1]

    def test_no_ui_prefix_special_case(self, tmp_path: Path):
        """Any file type merges the same; no src/fleet/ui diff special-casing remains."""
        import inspect

        from fleet.orchestrator import claim as claim_mod

        src = inspect.getsource(claim_mod)
        assert "src/fleet/ui" not in src
        assert "create_subprocess_exec" not in src
        assert "post_merge_command" in src
