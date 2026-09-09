"""Tests for orchestrator/spawn.py: plain spawn functions."""

from __future__ import annotations

import asyncio
import contextlib
import types
from pathlib import Path

from fleet.coders.opencode import OpencodeCoder
from fleet.core.config import RuntimeConfig
from fleet.core.task import Task
from fleet.orchestrator import spawn as spawn_mod
from fleet.orchestrator.spawn import (
    block_terminal,
    resolve_coder,
    should_isolate,
    spawn_worker,
)
from fleet.state import attempts
from tests.conftest import make_supervisor


class StubCoder:
    name = "stub"

    def build_argv(self, task, artifact_dir, plan=None):
        return ["echo"]

    def env(self, task, artifact_dir):
        return {}

    def normalize_event(self, raw_line):
        return None


class StubQueue:
    def __init__(self, status: str = "open") -> None:
        self._status = status
        self.released: list[tuple[str, str]] = []
        self.blocked: list[tuple[str, str]] = []
        self.comments: list[tuple[str, str]] = []
        self.frozen: list[tuple] = []
        self.isolation_infos: dict[str, tuple] = {}

    def claim_next(self, claimer_id, *, can_claim=None):
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


def _make_state(tmp_path: Path, queue: StubQueue, pinned: bool = True):
    sup = make_supervisor(
        tmp_path,
        queue=queue,  # type: ignore[arg-type]
        coder=StubCoder() if pinned else None,
        services=[],
        checks=[],
    )
    return sup.state


def _task(task_id: str = "t-001", **kw) -> Task:
    base = {"id": task_id, "title": "T", "description": None, "status": "open"}
    base.update(kw)
    return Task(**base)


def test_spawn_returns_record_with_attempt_n(tmp_path: Path) -> None:
    """spawn_worker returns a RunningWorker and does not touch st.running."""
    plain = tmp_path / "plain"
    plain.mkdir()
    queue = StubQueue()
    st = _make_state(tmp_path, queue)

    async def _run():
        worker = spawn_worker(st, _task(cwd=str(plain)))
        try:
            assert worker is not None
            assert worker.task.id == "t-001"
            assert worker.attempt_n == 1
            assert worker.run is not None
            assert worker.future is not None
            assert worker.started_at is not None
            assert st.running == {}
            task_dir = st.task_dir_for("t-001")
            assert attempts.current_attempt_n(task_dir) == 1
        finally:
            if worker is not None:
                worker.future.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await worker.future

    asyncio.run(_run())


def test_spawn_registers_nothing_on_second_attempt(tmp_path: Path) -> None:
    """A second spawn for another task still leaves st.running empty."""
    plain = tmp_path / "plain"
    plain.mkdir()
    queue = StubQueue()
    st = _make_state(tmp_path, queue)

    async def _run():
        first = spawn_worker(st, _task("t-a", cwd=str(plain)))
        second = spawn_worker(st, _task("t-b", cwd=str(plain)))
        try:
            assert first is not None and second is not None
            assert first.attempt_n == 1
            assert second.attempt_n == 1
            assert st.running == {}
        finally:
            for worker in (first, second):
                if worker is not None:
                    worker.future.cancel()
                    with contextlib.suppress(asyncio.CancelledError, Exception):
                        await worker.future

    asyncio.run(_run())


def test_spawn_invalid_coder_blocks_and_returns_none(tmp_path: Path) -> None:
    queue = StubQueue()
    st = _make_state(tmp_path, queue, pinned=False)
    st.config = RuntimeConfig(coder="bogus_typo")

    async def _run():
        return spawn_worker(st, _task("t-001"))

    assert asyncio.run(_run()) is None
    assert len(queue.blocked) == 1
    assert "invalid coder" in queue.blocked[0][1]
    assert "t-001" not in st.running


def test_spawn_bad_cwd_blocks_and_returns_none(tmp_path: Path) -> None:
    queue = StubQueue()
    st = _make_state(tmp_path, queue)
    task = _task("t-cwd", cwd=str(tmp_path / "does-not-exist"))

    async def _run():
        return spawn_worker(st, task)

    assert asyncio.run(_run()) is None
    assert len(queue.blocked) == 1
    assert "cwd is not a directory" in queue.blocked[0][1]
    assert "t-cwd" not in st.running


def test_spawn_unknown_worker_blocks_and_returns_none(tmp_path: Path, monkeypatch) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    queue = StubQueue()
    st = _make_state(tmp_path, queue)

    def _boom(task, ctx):
        raise ValueError("no worker for this bead")

    monkeypatch.setattr(spawn_mod, "select_worker", _boom)

    async def _run():
        return spawn_worker(st, _task("t-w", cwd=str(plain)))

    assert asyncio.run(_run()) is None
    assert len(queue.blocked) == 1
    assert "invalid worker" in queue.blocked[0][1]
    assert "t-w" not in st.running


def test_resolve_coder_prefers_pin(tmp_path: Path) -> None:
    sup = make_supervisor(tmp_path, services=[], checks=[])
    pin = StubCoder()
    sup.state.coder_pin = pin
    coder, name, model = resolve_coder(sup.state, _task())
    assert coder is pin
    assert name == "stub"


def test_resolve_coder_opencode_passes_default_model_not_limits(tmp_path: Path):
    """When coder_name == 'opencode', resolve_coder passes routing kwargs only."""

    queue = StubQueue()
    st = _make_state(tmp_path, queue, pinned=False)
    st.config = RuntimeConfig(coder="opencode", opencode_default_model="qwen3.6:latest")
    task = _task("t-opencode-01", cwd=str(tmp_path))

    coder, coder_name, model = resolve_coder(st, task)

    assert coder_name == "opencode"
    assert isinstance(coder, OpencodeCoder)
    assert coder.default_model == "qwen3.6:latest"
    assert coder.model == "sonnet"
    assert coder.context_limit == 200_000


def test_block_terminal_journals_blocks_comments(tmp_path: Path) -> None:
    queue = StubQueue()
    st = _make_state(tmp_path, queue)
    block_terminal(st, _task("t-t"), "terminal: no such coder")
    assert queue.blocked == [("t-t", "terminal: no such coder")]
    assert len(queue.comments) == 1
    outcomes = [
        e.get("outcome") for e in attempts.load_attempts(st.task_dir_for("t-t")) if e.get("outcome")
    ]
    assert outcomes == ["terminal"]


class TestShouldIsolate:
    def _stub(self, **cfg) -> types.SimpleNamespace:
        base = {"isolation": "worktree", "isolation_exclude": ""}
        base.update(cfg)
        return types.SimpleNamespace(config=types.SimpleNamespace(**base))

    def test_non_git_dir_runs_in_place(self, tmp_path: Path):
        assert should_isolate(self._stub(), _task(), None) is False

    def test_opt_out_metadata_runs_in_place(self, tmp_path: Path):
        repo = tmp_path / "repo"
        repo.mkdir()
        assert should_isolate(self._stub(), _task(isolation="none", cwd=str(repo)), repo) is False

    def test_config_none_runs_in_place(self, tmp_path: Path):
        repo = tmp_path / "repo"
        repo.mkdir()
        st = self._stub(isolation="none")
        assert should_isolate(st, _task(cwd=str(repo)), repo) is False

    def test_git_task_isolates_by_default(self, tmp_path: Path):
        repo = tmp_path / "repo"
        repo.mkdir()
        assert should_isolate(self._stub(), _task(cwd=str(repo)), repo) is True

    def test_task_without_cwd_never_isolates(self, tmp_path: Path):
        """No cwd means the task fell back to fleet's fleet_home; never worktree that."""
        repo = tmp_path / "repo"
        repo.mkdir()
        assert should_isolate(self._stub(), _task(cwd=None), repo) is False

    def test_excluded_repo_runs_in_place(self, tmp_path: Path):
        repo = tmp_path / "repo"
        repo.mkdir()
        st = self._stub(isolation_exclude=str(repo))
        assert should_isolate(st, _task(cwd=str(repo)), repo) is False
