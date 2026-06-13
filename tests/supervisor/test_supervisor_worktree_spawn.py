"""Tests for worktree isolation wired into the supervisor spawn path."""

from __future__ import annotations

import asyncio
from pathlib import Path

import structlog

from fleet.schemas import RuntimeConfig, Task
from fleet.supervisor import Supervisor


# ------ helpers -----------------------------------------------------------------


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
        self.blocked: list[tuple[str, str]] = []
        self.comments: list[tuple[str, str]] = []

    def claim_next(self, claimer_id):
        return None

    def release(self, task_id, reason=""):
        self.released.append((task_id, reason))

    def set_blocked(self, task_id, reason):
        self.blocked.append((task_id, reason))

    def close(self, task_id, reason="completed"):
        pass

    def comment(self, task_id, body):
        self.comments.append((task_id, body))

    def get(self, task_id):
        return Task(id=task_id, title="T", description=None, status=self._status)

    def list_ready(self, limit=50):
        return []


def _make_supervisor(tmp_path: Path, queue: StubQueue) -> Supervisor:
    s = Supervisor(
        coder=StubCoder(),
        queue=queue,
        runtime_toml_path=tmp_path / "runtime.toml",
        project_root=tmp_path,
        log=structlog.get_logger(),
    )
    s.config = RuntimeConfig(coder="claude")
    return s


# ------ _is_fleet_repo helper ------------------------------------------------


def test_is_fleet_repo_returns_correctly(tmp_path: Path) -> None:
    """_is_fleet_repo returns True for the fleet checkout, False for other dirs."""
    queue = StubQueue(status="open")
    s = _make_supervisor(tmp_path, queue)

    assert s._is_fleet_repo(tmp_path) is True
    assert s._is_fleet_repo(tmp_path / "invest") is False
    assert s._is_fleet_repo(tmp_path / "tasks" / "t-1") is False


# ------ worktree_isolation_enabled -- default-off guard --------------


def test_isolation_disabled_default(tmp_path: Path, monkeypatch) -> None:
    """FLEET_WORKTREE_ISOLATION unset → isolation is off."""
    from fleet.worktree import worktree_isolation_enabled

    assert worktree_isolation_enabled() is False


def test_isolation_disabled_explicitly_off(tmp_path: Path, monkeypatch) -> None:
    """FLEET_WORKTREE_ISOLATION=0 → isolation is off."""
    monkeypatch.setenv("FLEET_WORKTREE_ISOLATION", "0")
    from fleet.worktree import worktree_isolation_enabled

    assert worktree_isolation_enabled() is False


# ------ isolation enabled + cwd == project_root (fleet-repo task) -----

# The key assertion is that create_worktree is called with the right args
# and that a .worktree marker file appears.  We run in an event loop because
# _spawn_runner calls asyncio.create_task internally.


async def _spawn_runner_async(s: Supervisor, task: Task) -> None:
    r"""Helper: invoke _spawn_runner inside a running event loop."""
    s._spawn_runner(task)


def test_isolation_enabled_creates_worktree_and_marker(
    tmp_path: Path, monkeypatch
) -> None:
    """With the env set AND cwd == project_root, create_worktree is invoked
    and a .worktree marker file is written into the task dir.
    """
    worktree_calls: list = []
    fake_wt = tmp_path / "fake_worktree"
    fake_wt.mkdir()

    def _stub_create_worktree(repo_root, task_id, base_ref="main"):
        worktree_calls.append((repo_root, task_id, base_ref))
        return fake_wt

    monkeypatch.setenv("FLEET_WORKTREE_ISOLATION", "1")
    monkeypatch.setattr(
        "fleet.worktree.create_worktree",
        _stub_create_worktree,
    )

    queue = StubQueue(status="in_progress")
    s = _make_supervisor(tmp_path, queue)
    task = Task(id="t-wt-3", title="X", description=None, status="in_progress")

    async def _run() -> None:
        asyncio.create_task(asyncio.sleep(9999))
        await _spawn_runner_async(s, task)

    asyncio.run(_run())

    assert len(worktree_calls) == 1
    assert worktree_calls[0][0] == tmp_path
    assert worktree_calls[0][1] == "t-wt-3"
    assert worktree_calls[0][2] == "main"

    assert (tmp_path / "tasks" / "t-wt-3" / ".worktree").exists()
    marker_text = (tmp_path / "tasks" / "t-wt-3" / ".worktree").read_text()
    assert str(fake_wt) == marker_text

    runner = s._runners.get("t-wt-3")
    assert runner is not None
    assert runner._project_root == fake_wt


# ------ isolation enabled + cwd != project_root (non-fleet task) ------

# With env on but cwd is an invest/data dir → NO worktree, NO marker.


def test_isolation_enabled_with_non_fleet_cwd_no_worktree(
    tmp_path: Path, monkeypatch
) -> None:
    """With the env set but cwd != project_root (e.g. an invest task), NO
    worktree, NO marker.
    """
    worktree_calls: list = []

    def _stub_create_worktree(repo_root, task_id, base_ref="main"):
        worktree_calls.append((repo_root, task_id, base_ref))
        return tmp_path / "should_not_be_used"

    monkeypatch.setenv("FLEET_WORKTREE_ISOLATION", "1")
    monkeypatch.setattr(
        "fleet.worktree.create_worktree",
        _stub_create_worktree,
    )

    queue = StubQueue(status="in_progress")
    s = _make_supervisor(tmp_path, queue)
    invest_path = tmp_path / "invest"
    invest_path.mkdir()
    task = Task(
        id="t-wt-4",
        title="X",
        description=None,
        status="in_progress",
        cwd=str(invest_path),
    )

    async def _run() -> None:
        asyncio.create_task(asyncio.sleep(9999))
        await _spawn_runner_async(s, task)

    asyncio.run(_run())

    assert len(worktree_calls) == 0
    assert not (tmp_path / "tasks" / "t-wt-4" / ".worktree").exists()
    runner = s._runners.get("t-wt-4")
    assert runner is not None
    assert runner._project_root == invest_path
