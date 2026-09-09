"""Worktree isolation wired into the supervisor spawn path (git-aware)."""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

from fleet.core.config import RuntimeConfig
from fleet.core.task import Task
from fleet.orchestrator.spawn import spawn_worker
from fleet.orchestrator.supervisor import Supervisor
from tests.conftest import make_supervisor


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
        self.released: list[tuple[str, str]] = []
        self.blocked: list[tuple[str, str]] = []
        self.comments: list[tuple[str, str]] = []
        self.isolation_infos: dict[str, tuple] = {}
        self.frozen: list[tuple] = []

    def claim_next(self, claimer_id):
        return None

    def release(self, task_id, reason="", wait_sec=0):
        self.released.append((task_id, reason))

    def set_blocked(self, task_id, reason):
        self.blocked.append((task_id, reason))

    def close(self, task_id, reason="completed"):
        pass

    def comment(self, task_id, body):
        self.comments.append((task_id, body))

    def freeze_coder_model(self, task_id, coder, model):
        self.frozen.append((task_id, coder, model))

    def set_isolation_info(self, task_id, repo_root, base_ref, worktree_path):
        self.isolation_infos[task_id] = (repo_root, base_ref, worktree_path)

    def clear_isolation_info(self, task_id):
        self.isolation_infos.pop(task_id, None)

    def get(self, task_id):
        return Task(id=task_id, title="T", description=None, status=self._status)

    def list_ready(self, limit=50):
        return []


def _make_supervisor(
    tmp_path: Path, queue: StubQueue, config: RuntimeConfig | None = None
) -> Supervisor:
    (tmp_path / ".fleet").mkdir(parents=True, exist_ok=True)
    return make_supervisor(
        tmp_path,
        queue=queue,  # type: ignore[arg-type]
        config=config or RuntimeConfig(coder="claude"),
        coder=StubCoder(),  # type: ignore[arg-type]
        project_root=tmp_path / ".fleet",
        services=[],
        checks=[],
    )


def _git_init(path: Path) -> None:
    subprocess.run(["git", "init", "-b", "main"], cwd=path, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "t@t.com"], cwd=path, capture_output=True, check=False
    )
    subprocess.run(["git", "config", "user.name", "t"], cwd=path, capture_output=True, check=False)
    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", "init"],
        cwd=path,
        capture_output=True,
        check=True,
    )


def _spawn(s: Supervisor, task: Task):
    async def _run():
        return spawn_worker(s.state, task)

    return asyncio.run(_run())


def test_git_task_isolates_by_default(tmp_path: Path) -> None:
    """cwd inside a git repo + default config -> worktree + isolation info."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_init(repo)
    queue = StubQueue(status="in_progress")
    s = _make_supervisor(tmp_path, queue)
    task = Task(id="t-wt-1", title="X", description=None, status="in_progress", cwd=str(repo))
    worker = _spawn(s, task)

    assert "t-wt-1" in queue.isolation_infos
    repo_root, base_ref, wt_path = queue.isolation_infos["t-wt-1"]
    assert repo_root == str(repo)
    assert base_ref == "main"
    assert Path(wt_path).is_dir()
    assert worker is not None
    assert worker.run.ctx.project_root == Path(wt_path)
    assert "t-wt-1" not in s.state.running


def test_non_git_task_runs_in_place(tmp_path: Path) -> None:
    """cwd outside any repo -> no worktree, runs in cwd."""
    plain = tmp_path / "plain"
    plain.mkdir()
    queue = StubQueue(status="in_progress")
    s = _make_supervisor(tmp_path, queue)
    task = Task(id="t-wt-2", title="X", description=None, status="in_progress", cwd=str(plain))
    worker = _spawn(s, task)

    assert "t-wt-2" not in queue.isolation_infos
    assert worker is not None
    assert worker.run.ctx.project_root == plain


def test_opt_out_metadata_runs_in_place(tmp_path: Path) -> None:
    """fleet_isolation=none -> no worktree even inside a repo."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_init(repo)
    queue = StubQueue(status="in_progress")
    s = _make_supervisor(tmp_path, queue)
    task = Task(
        id="t-wt-3",
        title="X",
        description=None,
        status="in_progress",
        cwd=str(repo),
        isolation="none",
    )
    _spawn(s, task)

    assert "t-wt-3" not in queue.isolation_infos


def test_config_none_runs_in_place(tmp_path: Path) -> None:
    """config isolation=none -> no worktree even inside a repo."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_init(repo)
    queue = StubQueue(status="in_progress")
    s = _make_supervisor(tmp_path, queue, config=RuntimeConfig(isolation="none"))
    task = Task(id="t-wt-4", title="X", description=None, status="in_progress", cwd=str(repo))
    _spawn(s, task)

    assert "t-wt-4" not in queue.isolation_infos


def test_config_exclude_repo_runs_in_place(tmp_path: Path) -> None:
    """isolation_exclude listing the repo root -> no worktree for that repo only."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_init(repo)
    other = tmp_path / "other"
    other.mkdir()
    _git_init(other)
    queue = StubQueue(status="in_progress")
    cfg = RuntimeConfig(isolation_exclude=f"{tmp_path / 'unrelated'}, {repo}")
    s = _make_supervisor(tmp_path, queue, config=cfg)
    _spawn(s, Task(id="t-wt-x1", title="X", description=None, status="in_progress", cwd=str(repo)))
    _spawn(s, Task(id="t-wt-x2", title="X", description=None, status="in_progress", cwd=str(other)))

    assert "t-wt-x1" not in queue.isolation_infos
    assert "t-wt-x2" in queue.isolation_infos


def test_invalid_coder_leaves_no_worktree(tmp_path: Path) -> None:
    """Coder resolves FIRST: unknown coder blocks without creating a worktree."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_init(repo)
    queue = StubQueue(status="in_progress")
    (tmp_path / ".fleet").mkdir(parents=True, exist_ok=True)
    s = make_supervisor(
        tmp_path,
        queue=queue,  # type: ignore[arg-type]
        config=RuntimeConfig(coder="no-such-coder-xyz"),
        project_root=tmp_path / ".fleet",
        services=[],
        checks=[],
    )
    task = Task(id="t-wt-5", title="X", description=None, status="in_progress", cwd=str(repo))
    _spawn(s, task)

    assert len(queue.blocked) == 1
    assert "invalid coder" in queue.blocked[0][1]
    worktrees = tmp_path / ".fleet" / "worktrees"
    assert not worktrees.is_dir() or list(worktrees.iterdir()) == []
